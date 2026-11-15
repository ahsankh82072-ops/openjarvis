"""
Phase 1 vision test — tests describe_screen (needs moondream downloaded).
Run AFTER moondream pull completes:
    python test_phase1_vision.py
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

print("=" * 50)
print("PHASE 1 TEST — describe_screen (vision)")
print("=" * 50)

print("\n[1] Importing DescribeScreenTool...")
try:
    from openjarvis.tools.describe_screen import DescribeScreenTool
    print("    ✅ Import OK")
except Exception as e:
    print(f"    ❌ Import FAILED: {e}")
    sys.exit(1)

print("\n[2] Checking Ollama is reachable...")
import urllib.request, urllib.error
try:
    with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as r:
        import json
        data = json.loads(r.read())
        models = [m["name"] for m in data.get("models", [])]
        print(f"    ✅ Ollama running. Models: {models}")
        if not any("moondream" in m for m in models):
            print("    ⚠️  moondream not found in Ollama yet!")
            print("       Wait for 'ollama pull moondream' to finish, then rerun.")
            sys.exit(1)
except Exception as e:
    print(f"    ❌ Ollama not reachable: {e}")
    sys.exit(1)

print("\n[3] Asking 'What is on my screen?' ...")
print("    (This may take 20–60 seconds on CPU...)")
tool = DescribeScreenTool()
result = tool.execute(question="What is on this screen? List the main app and any visible text.")
if result.success:
    print("\n    ✅ Vision model replied:")
    print("    " + "-" * 44)
    for line in result.content.split("\n"):
        print("    " + line)
    print("    " + "-" * 44)
else:
    print(f"    ❌ FAILED: {result.content}")
    sys.exit(1)

print("\n" + "=" * 50)
print("PHASE 1 COMPLETE ✅")
print("=" * 50)
print("\nTell Jarvis 'go' to start Phase 2!")
