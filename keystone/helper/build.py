"""Builds ../projmap.dex from ProjMap.java.

javac compiles against the signature-only stubs in stubs/ (the real classes are on the device),
then d8 converts the class files to dex. d8 ships inside jadx's all-in-one jar.
Usage: python build.py [--d8-jar path/to/jadx-all.jar or r8.jar]
"""
import argparse
import glob
import os
import shutil
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))


def find(pattern_list, what):
    for p in pattern_list:
        hits = sorted(glob.glob(p))
        if hits:
            return hits[-1]
    raise SystemExit(f"{what} not found (looked in {pattern_list})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--d8-jar")
    args = ap.parse_args()
    javac = shutil.which("javac") or find([r"C:\Program Files\Java\jdk-*\bin\javac.exe"], "javac (a JDK)")
    java = os.path.join(os.path.dirname(javac), "java")
    d8_jar = args.d8_jar or find([os.path.join(REPO, "tools", "jadx", "lib", "jadx-*-all.jar")], "d8 (jadx-all.jar)")

    with tempfile.TemporaryDirectory() as tmp:
        stubs = os.path.join(tmp, "stubs")
        classes = os.path.join(tmp, "classes")
        stub_src = glob.glob(os.path.join(HERE, "stubs", "**", "*.java"), recursive=True)
        subprocess.run([javac, "--release", "8", "-nowarn", "-d", stubs, *stub_src], check=True)
        subprocess.run([javac, "--release", "8", "-nowarn", "-cp", stubs, "-d", classes,
                        os.path.join(HERE, "ProjMap.java")], check=True)
        # only ProjMap's own classes go in the dex; the stubs must resolve to the device's framework
        subprocess.run([java, "-cp", d8_jar, "com.android.tools.r8.D8", "--release", "--min-api", "29",
                        "--no-desugaring", "--output", tmp, *glob.glob(os.path.join(classes, "*.class"))], check=True)
        shutil.copy(os.path.join(tmp, "classes.dex"), os.path.join(os.path.dirname(HERE), "projmap.dex"))
    print("built projmap.dex")


if __name__ == "__main__":
    main()
