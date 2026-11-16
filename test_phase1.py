"""
Phase 1 test script — tests screen_capture tool in isolation.
Run from the OpenJarvis directory:
    python test_phase1.py

Does NOT require moondream/ollama to test the screenshot part.
"""

import sys, os
# Add the openjarvis package to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

print("=" * 50)
print("PHASE 1 TEST — screen_capture")
print("=" * 50)

# 1. Import the tool
print("\n[1] Importing ScreenCaptureTool...")
try:
    from openjarvis.tools.screen_capture import ScreenCaptureTool
    print("    ✅ Import OK")
except Exception as e:
    print(f"    ❌ Import FAILED: {e}")
    sys.exit(1)

# 2. Create instance and check spec
print("\n[2] Checking tool spec...")
tool = ScreenCaptureTool()
print(f"    Name        : {tool.spec.name}")
print(f"    Category    : {tool.spec.category}")
print(f"    Description : {tool.spec.description[:60]}...")
print("    ✅ Spec OK")

# 3. Take a screenshot
print("\n[3] Taking screenshot (monitor 1)...")
result = tool.execute(monitor=1, resize=True)
if result.success:
    img_size = len(result.content)  # base64 string length
    print(f"    ✅ Screenshot captured!")
    print(f"    Active window : {result.metadata.get('active_window')}")
    print(f"    Image size    : {result.metadata.get('size_bytes', '?')} bytes (PNG)")
    print(f"    Base64 length : {img_size} chars")
    print(f"    Capture time  : {result.metadata.get('capture_seconds')}s")
    # Save PNG to disk so you can open and verify it
    import base64
    png = base64.b64decode(result.content)
    out_path = os.path.join(os.path.dirname(__file__), "test_screenshot.png")
    with open(out_path, "wb") as f:
        f.write(png)
    print(f"\n    📸 Screenshot saved to: {out_path}")
    print("       Open it to verify it looks correct!")
else:
    print(f"    ❌ Screenshot FAILED: {result.content}")
    sys.exit(1)

print("\n" + "=" * 50)
print("TEST PASSED ✅")
print("=" * 50)
print("\nNext: once moondream finishes downloading,")
print("run:  python test_phase1_vision.py")
