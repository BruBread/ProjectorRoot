import struct, sys

# Pass your own dumped U-Boot image as argv[1] (default: ../backups/uboot.bin).
PATH = sys.argv[1] if len(sys.argv) > 1 else "../backups/uboot.bin"
BASE = 0x1FF800  # VA = file_offset + BASE  (confirmed for this build; re-derive for yours)
DO_BOOT_ANDROID_VA = 0x208774

with open(PATH, "rb") as f:
    data = f.read()

size = len(data)

def va_to_fo(va):
    return va - BASE

def fo_to_va(fo):
    return fo + BASE

def read_cstr(fo, maxlen=80):
    if fo < 0 or fo >= size:
        return None
    end = data.find(b"\x00", fo, min(fo + maxlen, size))
    if end == -1:
        return None
    if end == fo:
        return None
    s = data[fo:end]
    if len(s) < 2:
        return None
    for b in s:
        if b < 0x20 or b > 0x7e:
            return None
    return s.decode("ascii")

# Step 1: find "boot_android\0" string
needle = b"boot_android\x00"
idx = data.find(needle)
if idx == -1:
    print("FATAL: 'boot_android' string not found")
    sys.exit(1)
str_fo = idx
str_va = fo_to_va(str_fo)
print(f"[1] 'boot_android' string @ file_offset=0x{str_fo:x} VA=0x{str_va:x}")

# Step 2: find pointer to that string (8-byte LE) -> this is name_ptr field location
name_ptr_bytes = struct.pack("<Q", str_va)
name_ptr_hits = []
start = 0
while True:
    p = data.find(name_ptr_bytes, start)
    if p == -1:
        break
    name_ptr_hits.append(p)
    start = p + 1
print(f"[2] found {len(name_ptr_hits)} pointer(s) to the 'boot_android' string: "
      + ", ".join(f"0x{h:x}" for h in name_ptr_hits))

# Step 3: find pointer to DO_BOOT_ANDROID_VA (8-byte LE) near each name_ptr hit
cmd_ptr_bytes = struct.pack("<Q", DO_BOOT_ANDROID_VA)
cmd_ptr_hits = []
start = 0
while True:
    p = data.find(cmd_ptr_bytes, start)
    if p == -1:
        break
    cmd_ptr_hits.append(p)
    start = p + 1
print(f"[3] found {len(cmd_ptr_hits)} pointer(s) to do_boot_android (0x{DO_BOOT_ANDROID_VA:x}): "
      + ", ".join(f"0x{h:x}" for h in cmd_ptr_hits))

# pair them up: for each name_ptr hit, find nearest cmd_ptr hit within 0x40 bytes
struct_start = None
cmd_field_offset = None
for nph in name_ptr_hits:
    for cph in cmd_ptr_hits:
        if 0 <= (cph - nph) <= 0x40:
            struct_start = nph
            cmd_field_offset = cph - nph
            print(f"[4] MATCHED struct: name_ptr field @ 0x{nph:x}, cmd_ptr field @ 0x{cph:x}, "
                  f"cmd_field_offset={cmd_field_offset}")
            break
    if struct_start is not None:
        break

if struct_start is None:
    print("FATAL: could not correlate name_ptr and cmd_ptr fields into one struct")
    sys.exit(1)

# Step 4: figure out usage_ptr / help_ptr fields by scanning the bytes between
# cmd_field_offset+8 and cmd_field_offset+40 for plausible string pointers
print(f"\n[5] raw struct bytes from 0x{struct_start:x} (+0x50):")
for off in range(0, 0x50, 8):
    fo = struct_start + off
    if fo + 8 > size:
        break
    val = struct.unpack_from("<Q", data, fo)[0]
    maybe_str = None
    maybe_fo = va_to_fo(val)
    s = read_cstr(maybe_fo)
    tag = ""
    if off == 0:
        tag = " <- name_ptr"
    if off == cmd_field_offset:
        tag = " <- cmd_ptr (do_boot_android)"
    print(f"    +0x{off:02x}: raw=0x{val:016x} -> fo=0x{maybe_fo:x}" +
          (f" str={s!r}" if s else "") + tag)
