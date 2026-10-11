import struct, sys

def read_uleb128(data, off):
    result = 0
    shift = 0
    while True:
        b = data[off]
        off += 1
        result |= (b & 0x7f) << shift
        if not (b & 0x80):
            break
        shift += 7
    return result, off

def mutf8_decode(data, off):
    # read until null byte, decode as modified UTF-8 (close enough with utf-8 errors=replace for our grep purposes)
    end = data.index(b'\x00', off)
    return data[off:end].decode('utf-8', errors='replace')

def dex_strings(path):
    with open(path, 'rb') as f:
        data = f.read()
    string_ids_size, string_ids_off = struct.unpack_from('<II', data, 56)
    strings = []
    for i in range(string_ids_size):
        str_data_off = struct.unpack_from('<I', data, string_ids_off + i*4)[0]
        _, data_start = read_uleb128(data, str_data_off)
        s = mutf8_decode(data, data_start)
        strings.append(s)
    return strings

if __name__ == '__main__':
    path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else None
    strings = dex_strings(path)
    if out_path:
        with open(out_path, 'w', encoding='utf-8') as f:
            for s in strings:
                f.write(s + '\n')
    else:
        for s in strings:
            print(s)
