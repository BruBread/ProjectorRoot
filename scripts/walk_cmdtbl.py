import struct, sys

# Pass your own dumped U-Boot image as argv[1] (default: ../backups/uboot.bin).
PATH = sys.argv[1] if len(sys.argv) > 1 else "../backups/uboot.bin"
BASE = 0x1FF800
STRIDE = 0x30
ANCHOR = 0xdb928  # boot_android cmd_tbl entry file offset (specific to this build)

with open(PATH, "rb") as f:
    data = f.read()
size = len(data)

def va_to_fo(va):
    return va - BASE

def read_cstr(fo, maxlen=100):
    if fo is None or fo < 0 or fo >= size:
        return None
    end = data.find(b"\x00", fo, min(fo + maxlen, size))
    if end == -1 or end == fo:
        return None
    s = data[fo:end]
    if len(s) < 1:
        return None
    for b in s:
        if b < 0x20 or b > 0x7e:
            return None
    return s.decode("ascii")

def parse_entry(fo):
    if fo < 0 or fo + 0x30 > size:
        return None
    name_va, margs_rep, cmd_va, usage_va, help_va, complete_va = struct.unpack_from("<QQQQQQ", data, fo)
    maxargs = margs_rep & 0xffffffff
    repeatable = (margs_rep >> 32) & 0xffffffff
    name_fo = va_to_fo(name_va)
    name = read_cstr(name_fo)
    if name is None or len(name) == 0 or len(name) > 40:
        return None
    # basic sanity on name chars: printable, looks like a command token
    for c in name:
        if not (c.isalnum() or c in "_-"):
            return None
    cmd_fo = va_to_fo(cmd_va)
    # code region roughly 0x800..0x300000 in this dump (u-boot proper); must be 4-aligned (AArch64 insn)
    if not (0x800 <= cmd_fo < 0x300000):
        return None
    if cmd_fo % 4 != 0:
        return None
    usage_fo = va_to_fo(usage_va)
    usage = read_cstr(usage_fo)
    return {
        "fo": fo, "name": name, "name_va": name_va, "maxargs": maxargs,
        "repeatable": repeatable, "cmd_va": cmd_va, "cmd_fo": cmd_fo,
        "usage": usage, "help_va": help_va, "complete_va": complete_va,
    }

# sanity check anchor
anchor_entry = parse_entry(ANCHOR)
print("ANCHOR entry:", anchor_entry)
assert anchor_entry is not None and anchor_entry["name"] == "boot_android"

entries = {}
entries[ANCHOR] = anchor_entry

# walk forward
fo = ANCHOR + STRIDE
while True:
    e = parse_entry(fo)
    if e is None:
        print(f"forward walk stopped at fo=0x{fo:x} (invalid entry)")
        break
    entries[fo] = e
    fo += STRIDE

# walk backward
fo = ANCHOR - STRIDE
while True:
    e = parse_entry(fo)
    if e is None:
        print(f"backward walk stopped at fo=0x{fo:x} (invalid entry)")
        break
    entries[fo] = e
    fo -= STRIDE

print(f"\nTotal entries found: {len(entries)}")
print(f"Table spans file offsets 0x{min(entries):x} .. 0x{max(entries):x}\n")

for fo in sorted(entries):
    e = entries[fo]
    marker = ""
    if e["name"] in ("boot_fit", "bootrkp", "boot_android"):
        marker = "  <=== TARGET"
    print(f"0x{fo:06x}: {e['name']:20s} maxargs={e['maxargs']:<3d} rep={e['repeatable']:<2d} "
          f"cmd_va=0x{e['cmd_va']:08x} cmd_fo=0x{e['cmd_fo']:06x}  usage={e['usage']!r}{marker}")
