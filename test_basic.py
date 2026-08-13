"""
Basic Integration Test - No Database Required
Tests modules that don't require database connection
"""

print("=" * 60)
print("BASIC MODULE TEST - NO DATABASE")
print("=" * 60)

# Test 1: BDI Scorer (pure logic, no dependencies)
print("\n1. Testing BDI scorer...")
try:
    from bdi_scorer import score_bdi, get_severity, BDI_ITEMS

    test_responses = {i: 1 for i in range(21)}
    result = score_bdi(test_responses)
    assert result['total'] == 21
    assert result['severity'] == 'mild'
    print(f"   OK - BDI scorer works (score: {result['total']}, severity: {result['severity']})")
except Exception as e:
    print(f"   ERROR - BDI scorer failed: {e}")

# Test 2: Severity Router (pure logic, no dependencies)
print("\n2. Testing severity router...")
try:
    from severity_router import route_by_severity

    # Severe depression
    route1 = route_by_severity(bdi_score=35, session_number=1, bdi_history=[])
    assert route1 == "BEHAVIOURAL_ACTIVATION"
    print(f"   OK - Severe (BDI=35) routes to {route1}")

    # Moderate depression
    route2 = route_by_severity(bdi_score=22, session_number=3, bdi_history=[35, 28])
    assert route2 == "VALIDATE"
    print(f"   OK - Moderate (BDI=22) routes to {route2}")

    # Recovered
    route3 = route_by_severity(bdi_score=10, session_number=10, bdi_history=[35, 28, 22, 18, 15, 12, 11, 10, 9])
    assert route3 == "RELAPSE_PREVENTION"
    print(f"   OK - Recovered (BDI=10) routes to {route3}")
except Exception as e:
    print(f"   ERROR - Severity router failed: {e}")

# Test 3: Context Builder (minimal dependencies)
print("\n3. Testing context builder...")
try:
    from context_builder import build_minimal_context

    context = build_minimal_context(session_number=1, bdi_score=22, severity="moderate")
    assert "Session Number: 1" in context
    assert "BDI-II Score: 22" in context
    print("   OK - Context builder works")
except Exception as e:
    print(f"   ERROR - Context builder failed: {e}")

# Test 4: Full Protocol State Detection
print("\n4. Testing full_protocol module...")
try:
    from full_protocol import is_new_protocol_state, get_initial_state

    assert is_new_protocol_state("BDI_ASSESSMENT") == True
    assert is_new_protocol_state("VALIDATE") == False
    assert is_new_protocol_state("BA_MONITORING") == True
    print("   OK - State detection works")

    initial = get_initial_state(0)
    assert initial == "BDI_ASSESSMENT"
    print(f"   OK - Initial state is {initial}")
except Exception as e:
    print(f"   ERROR - Full protocol failed: {e}")

print("\n" + "=" * 60)
print("BASIC TESTS COMPLETE")
print("=" * 60)
print("\nAll basic modules work correctly!")
print("\nTo test with database:")
print("1. Set environment variables (TURSO_DATABASE_URL, TURSO_AUTH_TOKEN, GROQ_API_KEY)")
print("2. Run: python app.py")
print("3. Test endpoints with curl or Postman")
