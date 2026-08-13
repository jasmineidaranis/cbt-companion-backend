"""
ML Inference Module
Uses Multi-Scale Temporal Transformer Autoencoder (TCN_Transformer_AE) to detect
stress/depression risk from wearable sensor data. Anomaly detection via reconstruction error.

Architecture (matches training code exactly):
  - WINDOW_SIZE = 10  (feature extraction window)
  - SEQ_LEN     = 8   (sequence fed to model)
  - input_size  = 12  features per window
  - TransformerBlock: MultiheadAttention(dim=64, heads=4) + LayerNorm + FFN(64->128->64)
  - Threshold embedded in checkpoint (95th-percentile of training errors)
  - Scaler embedded in checkpoint (StandardScaler fitted on training data)

12 Features (in order):
  0  mean_gsr
  1  std_gsr           (+1e-6 epsilon)
  2  slope_gsr         = (last - first) / WINDOW_SIZE
  3  gsr_diff          = mean(abs(diff(gsr_w)))
  4  mean_ppg
  5  std_ppg           (+1e-6 epsilon)
  6  ppg_energy        = sum(ppg_w ** 2)
  7  ppg_variability   = std(diff(ppg_w))
  8  mean_motion
  9  motion_std
  10 motion_energy     = sum(motion ** 2)
  11 motion_ratio      = fraction of samples above 75th percentile of window
"""

import warnings
import io
import numpy as np
import torch
import torch.nn as nn
from pathlib import Path


# ===============================
# TRANSFORMER BLOCK
# ===============================

class TransformerBlock(nn.Module):
    def __init__(self, dim=64, heads=4):
        super().__init__()
        self.attn  = nn.MultiheadAttention(dim, heads, batch_first=True)
        self.norm1 = nn.LayerNorm(dim)
        self.norm2 = nn.LayerNorm(dim)
        self.ff    = nn.Sequential(
            nn.Linear(dim, dim * 2),
            nn.ReLU(),
            nn.Linear(dim * 2, dim),
        )

    def forward(self, x):
        # x: (batch, time, dim)
        attn_out, _ = self.attn(x, x, x)
        x = self.norm1(x + attn_out)
        x = self.norm2(x + self.ff(x))
        return x


# ===============================
# TCN + TRANSFORMER AUTOENCODER
# ===============================

class TCN_Transformer_AE(nn.Module):
    def __init__(self, input_size=12):
        super().__init__()

        self.branch1 = nn.Conv1d(input_size, 32, 3, padding=1)
        self.branch2 = nn.Conv1d(input_size, 32, 5, padding=2)
        self.branch3 = nn.Conv1d(input_size, 32, 7, padding=3)

        self.bn1  = nn.BatchNorm1d(32)
        self.bn2  = nn.BatchNorm1d(32)
        self.bn3  = nn.BatchNorm1d(32)
        self.relu = nn.LeakyReLU(0.1)

        self.merge       = nn.Conv1d(96, 64, 1)
        self.transformer = TransformerBlock(dim=64, heads=4)
        self.expand      = nn.Conv1d(64, 96, 1)

        self.dec1 = nn.Conv1d(96, input_size, 3, padding=1)
        self.dec2 = nn.Conv1d(96, input_size, 5, padding=2)
        self.dec3 = nn.Conv1d(96, input_size, 7, padding=3)

    def forward(self, x):
        # x: (batch, time, features)
        x = x.permute(0, 2, 1)                             # (batch, features, time)

        b1 = self.relu(self.bn1(self.branch1(x)))
        b2 = self.relu(self.bn2(self.branch2(x)))
        b3 = self.relu(self.bn3(self.branch3(x)))

        x = torch.cat([b1, b2, b3], dim=1)                 # (batch, 96, time)
        x = self.relu(self.merge(x))                        # (batch, 64, time)

        x = x.permute(0, 2, 1)                             # (batch, time, 64)
        x = self.transformer(x)                             # (batch, time, 64)
        x = x.permute(0, 2, 1)                             # (batch, 64, time)

        x  = self.relu(self.expand(x))                      # (batch, 96, time)

        d1 = self.dec1(x)
        d2 = self.dec2(x)
        d3 = self.dec3(x)

        recon = (d1 + d2 + d3) / 3.0
        return recon.permute(0, 2, 1)                       # (batch, time, features)


# ===============================
# MODEL SINGLETON
# ===============================

class ModelSingleton:
    _instance   = None
    _model      = None
    _scaler     = None
    _threshold  = None
    _device     = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load_model(self):
        if self._model is not None:
            return self._model

        try:
            self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

            models_dir  = Path(__file__).parent / "models"
            model_path  = models_dir / "TCN_Transformer_AE_full_model.pth.zip"

            if not model_path.exists():
                raise FileNotFoundError(f"Model file not found: {model_path}")

            # Checkpoint bundles model_state_dict + scaler + threshold
            with open(model_path, "rb") as f:
                data = io.BytesIO(f.read())

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                checkpoint = torch.load(data, map_location=self._device,
                                        weights_only=False)

            self._model = TCN_Transformer_AE(input_size=12)
            self._model.load_state_dict(checkpoint["model_state_dict"])
            self._model.to(self._device)
            self._model.eval()

            self._scaler    = checkpoint["scaler"]
            self._threshold = float(checkpoint["threshold"])

            print(f"[ML] TCN_Transformer_AE loaded on {self._device} | threshold={self._threshold:.6f}")
            return self._model

        except Exception as e:
            print(f"[ML] Error loading model: {e}")
            raise

    def get_model(self):
        if self._model is None:
            self.load_model()
        return self._model

    def get_scaler(self):
        if self._scaler is None:
            self.load_model()
        return self._scaler

    def get_threshold(self):
        if self._threshold is None:
            self.load_model()
        return self._threshold

    def get_device(self):
        if self._device is None:
            self.load_model()
        return self._device


# Global singleton
model_singleton = ModelSingleton()


# ===============================
# FEATURE EXTRACTION CONSTANTS
# ===============================

WINDOW_SIZE  = 10                              # must match training
SEQ_LEN      = 8                               # must match training
MIN_READINGS = SEQ_LEN + WINDOW_SIZE - 1      # = 17 minimum raw readings


def extract_features_from_window(ppg_w, gsr_w, acc_x_w, acc_y_w, acc_z_w):
    """
    Extract 12 features from a window of raw sensor samples.
    Exactly matches training feature extraction.

    Features (same order scaler was trained on):
      0  mean_gsr
      1  std_gsr       (+1e-6 epsilon)
      2  slope_gsr     = (last - first) / WINDOW_SIZE
      3  gsr_diff      = mean(abs(diff(gsr_w)))
      4  mean_ppg
      5  std_ppg       (+1e-6 epsilon)
      6  ppg_energy    = sum(ppg_w ** 2)
      7  ppg_variability = std(diff(ppg_w))
      8  mean_motion
      9  motion_std
      10 motion_energy = sum(motion ** 2)
      11 motion_ratio  = fraction of samples above 75th percentile of window
    """
    ppg_w  = np.array(ppg_w,  dtype=float)
    gsr_w  = np.array(gsr_w,  dtype=float)
    acc_x_w = np.array(acc_x_w, dtype=float)
    acc_y_w = np.array(acc_y_w, dtype=float)
    acc_z_w = np.array(acc_z_w, dtype=float)

    motion = np.sqrt(acc_x_w**2 + acc_y_w**2 + acc_z_w**2)

    mean_gsr  = np.mean(gsr_w)
    std_gsr   = np.std(gsr_w) + 1e-6
    slope_gsr = (gsr_w[-1] - gsr_w[0]) / WINDOW_SIZE
    gsr_diff  = np.mean(np.abs(np.diff(gsr_w)))

    mean_ppg        = np.mean(ppg_w)
    std_ppg         = np.std(ppg_w) + 1e-6
    ppg_energy      = np.sum(ppg_w ** 2)
    ppg_variability = np.std(np.diff(ppg_w))

    mean_motion   = np.mean(motion)
    motion_std    = np.std(motion)
    motion_energy = np.sum(motion ** 2)
    motion_ratio  = float(np.mean(motion > np.percentile(motion, 75)))

    return [
        mean_gsr, std_gsr, slope_gsr, gsr_diff,
        mean_ppg, std_ppg, ppg_energy, ppg_variability,
        mean_motion, motion_std, motion_energy, motion_ratio,
    ]


def prepare_sensor_data(raw_readings):
    """
    Prepare raw sensor readings for autoencoder inference.

    Args:
        raw_readings: list of dicts with keys ppg, gsr, acc_x, acc_y, acc_z
                      ordered oldest -> newest (minimum MIN_READINGS = 17)

    Returns:
        numpy array shape (1, SEQ_LEN, 12) scaled and ready for model, or None
    """
    if len(raw_readings) < MIN_READINGS:
        return None

    # Take last MIN_READINGS readings (17 = SEQ_LEN + WINDOW_SIZE - 1)
    readings = raw_readings[-MIN_READINGS:]

    ppg_vals  = [r['ppg']   for r in readings]
    gsr_vals  = [r['gsr']   for r in readings]
    acc_x_vals = [r['acc_x'] for r in readings]
    acc_y_vals = [r['acc_y'] for r in readings]
    acc_z_vals = [r['acc_z'] for r in readings]

    # SEQ_LEN=8 windows of WINDOW_SIZE=10, stride 1
    # window i covers readings[i : i+WINDOW_SIZE]
    windows = []
    for i in range(SEQ_LEN):
        feat = extract_features_from_window(
            ppg_vals [i:i + WINDOW_SIZE],
            gsr_vals [i:i + WINDOW_SIZE],
            acc_x_vals[i:i + WINDOW_SIZE],
            acc_y_vals[i:i + WINDOW_SIZE],
            acc_z_vals[i:i + WINDOW_SIZE],
        )
        windows.append(feat)

    feature_seq = np.array(windows, dtype=np.float32)        # (8, 12)

    scaler      = model_singleton.get_scaler()
    feature_seq = scaler.transform(feature_seq).astype(np.float32)
    feature_seq = np.nan_to_num(feature_seq)

    return np.expand_dims(feature_seq, axis=0)                # (1, 8, 12)


# ===============================
# PREDICTION
# ===============================

def predict_risk(raw_readings):
    """
    Predict stress/depression risk using autoencoder reconstruction error.

    Args:
        raw_readings: list of recent sensor reading dicts (min MIN_READINGS = 17)
                      each dict: {ppg, gsr, acc_x, acc_y, acc_z}

    Returns:
        dict with prediction, risk_level, confidence, message  -- or None on error
    """
    try:
        features = prepare_sensor_data(raw_readings)

        if features is None:
            return {
                "prediction": "INSUFFICIENT_DATA",
                "risk_level": -1,
                "confidence": 0.0,
                "message":    f"Need at least {MIN_READINGS} readings for prediction"
            }

        model     = model_singleton.get_model()
        device    = model_singleton.get_device()
        threshold = model_singleton.get_threshold()

        x = torch.tensor(features, dtype=torch.float32).to(device)

        with torch.no_grad():
            recon = model(x)
            error = torch.mean((recon - x) ** 2).item()

        high_risk  = error > threshold
        risk_level = 2 if high_risk else 0
        prediction = "HIGH_RISK" if high_risk else "NORMAL"

        if high_risk:
            confidence = min(1.0, error / (2 * threshold))
        else:
            confidence = min(1.0, 1.0 - error / threshold)
        confidence = max(0.0, round(confidence, 3))

        messages = {
            0: "User appears to be in normal mental state",
            2: "Elevated stress/depression risk detected - monitoring recommended"
        }

        print(f"[ML] recon_error={error:.6f} threshold={threshold:.6f} -> {prediction} ({confidence:.0%})")

        return {
            "prediction": prediction,
            "risk_level": risk_level,
            "confidence": confidence,
            "message":    messages[risk_level]
        }

    except Exception as e:
        print(f"[ML] Error during inference: {e}")
        import traceback
        traceback.print_exc()
        return None


# ===============================
# INITIALIZATION
# ===============================

def initialize_model():
    """Load model at startup."""
    try:
        model_singleton.load_model()
        return True
    except Exception as e:
        print(f"[ML] Model initialization failed: {e}")
        return False
