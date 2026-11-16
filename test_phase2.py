"""
Phase 2 test script — tests computer_action safety mechanisms and dry-run execution.
Run from OpenJarvis directory:
    python test_phase2.py
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

print("=" * 60)
print("PHASE 2 TEST — computer_action (Safety & Controls)")
print("=" * 60)

# 1. Import
print("\n[1] Importing ComputerActionTool...")
try:
    from openjarvis.tools.computer_action import ComputerActionTool, reset_step_counter
    print("    ✅ Import OK")
except Exception as e:
    print(f"    ❌ Import FAILED: {e}")
    sys.exit(1)

tool = ComputerActionTool()
reset_step_counter()

# 2. Spec test
print("\n[2] Checking tool specification...")
print(f"    Tool ID     : {tool.spec.name}")
print(f"    Category    : {tool.spec.category}")
print(f"    Actions     : {tool.spec.parameters['properties']['action']['enum']}")
print("    ✅ Spec OK")

# 3. Dry-run test
print("\n[3] Testing DRY RUN mode (no physical mouse/keyboard action)...")
res1 = tool.execute(action="click", x=500, y=300, dry_run=True)
print(f"    Result      : {res1.content}")
print(f"    Metadata    : {res1.metadata}")
assert res1.success is True
assert res1.metadata.get("dry_run") is True
print("    ✅ Dry-run click passed!")

res2 = tool.execute(action="type", text="Hello OpenJarvis", dry_run=True)
print(f"    Result      : {res2.content}")
assert res2.success is True
print("    ✅ Dry-run type passed!")

# 4. Sensitive keyword safety block test
print("\n[4] Testing SENSITIVE KEYWORD blocking (safety)...")
res_safe = tool.execute(action="type", text="Enter my bank password now", dry_run=True)
print(f"    Result      : {res_safe.content}")
assert res_safe.success is False
assert res_safe.metadata.get("security_block") is True
print("    ✅ Safety block blocked sensitive typing successfully!")

# 5. Emergency stop test
print("\n[5] Testing EMERGENCY STOP...")
res_stop = tool.execute(action="emergency_stop")
print(f"    Result      : {res_stop.content}")
assert res_stop.success is False
assert res_stop.metadata.get("emergency_stop") is True

# Verify subsequent action is rejected due to emergency stop
res_blocked = tool.execute(action="click", dry_run=True)
print(f"    Subsequent  : {res_blocked.content}")
assert res_blocked.success is False
print("    ✅ Emergency stop lock verified!")

# Reset state
reset_step_counter()
print("    ✅ Reset step counter OK")

# 6. Max 15 steps ceiling test
print("\n[6] Testing 15-STEP safety limit ceiling...")
for step in range(15):
    r = tool.execute(action="scroll", clicks=1, dry_run=True)
    assert r.success is True
# Step 16 must be blocked
r_limit = tool.execute(action="scroll", clicks=1, dry_run=True)
print(f"    16th Step   : {r_limit.content}")
assert r_limit.success is False
assert r_limit.metadata.get("step_limit_reached") is True
print("    ✅ 15-step safety ceiling enforced successfully!")

# Reset state for real use
reset_step_counter()

print("\n" + "=" * 60)
print("ALL PHASE 2 SAFETY & DRY-RUN TESTS PASSED ✅")
print("=" * 60)
