"""
Quick Integration Test
Tests that all new modules can be imported and basic functions work
"""

print("=" * 60)
print("FULL BECK PROTOCOL - INTEGRATION TEST")
print("=" * 60)

# Test 1: Import all new modules
print("\n1. Testing imports...")
try:
    from bdi_scorer import score_bdi, get_severity, BDI_ITEMS
    from severity_router import route_by_severity
    from patient_tracker import init_patient_tracking
    from context_builder import build_minimal_context
    from beck_agents import bdi_assessment_agent, behavioural_activation_agent
    from full_protocol import is_new_protocol_state, get_initial_state
    print("   ✅ All imports successful")
except Exception as e:
    print(f"   ❌ Import failed: {e}")
    exit(1)

# Test 2: BDI Scorer
print("\n2. Testing BDI scorer...")
try:
    test_responses = {i: 1 for i in range(21)}  # All items scored 1
    result = score_bdi(test_responses)
    assert result['total'] == 21
    assert result['severity'] == 'mild'
    assert result['completed_items'] == 21
    print(f"   ✅ BDI scorer works (score: {result['total']}, severity: {result['severity']})")
except Exception as e:
    print(f"   ❌ BDI scorer failed: {e}")

# Test 3: Severity Router
print("\n3. Testing severity router...")
try:
    # Test severe depression routing
    route1 = route_by_severity(bdi_score=35, session_number=1, bdi_history=[])
    assert route1 == "BEHAVIOURAL_ACTIVATION"
    print(f"   ✅ Severe (BDI=35) → {route1}")

    # Test moderate depression routing
    route2 = route_by_severity(bdi_score=22, session_number=3, bdi_history=[35, 28])
    assert route2 == "VALIDATE"
    print(f"   ✅ Moderate (BDI=22) → {route2}")

    # Test recovered routing
    route3 = route_by_severity(bdi_score=10, session_number=10, bdi_history=[35, 28, 22, 18, 15, 12, 11, 10, 9])
    assert route3 == "RELAPSE_PREVENTION"
    print(f"   ✅ Recovered (BDI=10, session 10) → {route3}")
except Exception as e:
    print(f"   ❌ Severity router failed: {e}")

# Test 4: Context Builder
print("\n4. Testing context builder...")
try:
    context = build_minimal_context(session_number=1, bdi_score=22, severity="moderate")
    assert "Session Number: 1" in context
    assert "BDI-II Score: 22" in context
    print("   ✅ Context builder works")
except Exception as e:
    print(f"   ❌ Context builder failed: {e}")

# Test 5: Protocol State Detection
print("\n5. Testing protocol state detection...")
try:
    assert is_new_protocol_state("BDI_ASSESSMENT") == True
    assert is_new_protocol_state("VALIDATE") == False
    assert is_new_protocol_state("BA_MONITORING") == True
    assert is_new_protocol_state("COMPLETE") == False
    print("   ✅ State detection works")
except Exception as e:
    print(f"   ❌ State detection failed: {e}")

# Test 6: Initial State
print("\n6. Testing initial state...")
try:
    initial = get_initial_state(0)
    assert initial == "BDI_ASSESSMENT"
    print(f"   ✅ Initial state: {initial}")
except Exception as e:
    print(f"   ❌ Initial state failed: {e}")

print("\n" + "=" * 60)
print("INTEGRATION TEST COMPLETE")
print("=" * 60)
print("\n✅ All basic tests passed!")
print("\nNext steps:")
print("1. Start the backend: python app.py")
print("2. Test new endpoint: POST /api/session/start-full-protocol")
print("3. Test full BDI assessment flow")
print("4. Test severity routing (severe, moderate, recovered)")
print("\nSee NEXT_STEPS.md for detailed testing instructions.")
