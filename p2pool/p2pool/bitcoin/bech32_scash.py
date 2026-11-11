"""
BIP-173 Bech32 encoder/decoder for Scash native SegWit addresses (scash1q... / tcash1q...).
Allows miners to pass scash1... addresses directly to -a or Stratum username.
"""
CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

def bech32_polymod(values):
    generator = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]
    chk = 1
    for value in values:
        top = chk >> 25
        chk = (chk & 0x1ffffff) << 5 ^ value
        for i in range(5):
            chk ^= generator[i] if ((top >> i) & 1) else 0
    return chk

def bech32_hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]

def bech32_verify_checksum(hrp, data):
    return bech32_polymod(bech32_hrp_expand(hrp) + data) == 1

def bech32_create_checksum(hrp, data):
    values = bech32_hrp_expand(hrp) + data
    polymod = bech32_polymod(values + [0, 0, 0, 0, 0, 0]) ^ 1
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]

def convertbits(data, frombits, tobits, pad=True):
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    max_acc = (1 << (frombits + tobits - 1)) - 1
    for value in data:
        if value < 0 or (value >> frombits):
            return None
        acc = ((acc << frombits) | value) & max_acc
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        return None
    return ret

def decode_scash_address(addr, expected_hrp='scash'):
    if not addr:
        return None, None
    addr = addr.strip().lower()
    pos = addr.rfind('1')
    if pos < 1 or pos + 7 > len(addr) or len(addr) > 90:
        return None, None
    hrp = addr[:pos]
    if expected_hrp and hrp != expected_hrp:
        return None, None
    data = [CHARSET.find(x) for x in addr[pos + 1:]]
    if any(x == -1 for x in data) or not bech32_verify_checksum(hrp, data):
        return None, None
    decoded = convertbits(data[1:-6], 5, 8, False)
    if decoded is None or len(decoded) != 20:
        return None, None
    return data[0], ''.join(chr(b) for b in decoded)

def encode_scash_address(pubkey_hash_bytes, hrp='scash', witver=0):
    data = [witver] + convertbits([ord(c) for c in pubkey_hash_bytes], 8, 5, True)
    checksum = bech32_create_checksum(hrp, data)
    return hrp + '1' + ''.join(CHARSET[d] for d in data + checksum)
