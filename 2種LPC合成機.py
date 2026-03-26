import numpy as np

def lpc_to_parcor(lpc):
    """LPC係数をPARCOR(反射係数)に変換する（安定性を保つため）"""
    m = len(lpc)
    k = np.zeros(m)
    a = np.copy(lpc)
    for i in range(m - 1, -1, -1):
        k[i] = a[i]
        if i == 0: break
        # ハウリング防止のクリッピング
        if abs(k[i]) >= 1.0:
            k[i] = np.sign(k[i]) * 0.999
        
        # 次数を下げる再帰計算（ステップダウン）
        denom = 1.0 - k[i]**2
        a_new = (a[:i] - k[i] * a[:i][::-1]) / denom
        a = a_new
    return k

def parcor_to_lpc(k):
    """PARCORをLPC係数に戻す（ステップアップ）"""
    m = len(k)
    a = np.zeros(m)
    for i in range(m):
        if i == 0:
            a[0] = k[0]
        else:
            a_prev = np.copy(a[:i])
            a[i] = k[i]
            for j in range(i):
                a[j] = a_prev[j] + k[i] * a_prev[i - 1 - j]
    return a

def merge_lpc(lpc_a, lpc_b, ratio=0.5):
    """
    2つのLPCを比率(ratio)で合成する
    ratio=0.0 で Aの声, ratio=1.0 で Bの声
    """
    # PARCOR空間に変換
    k_a = lpc_to_parcor(lpc_a)
    k_b = lpc_to_parcor(lpc_b)
    
    # 線形補間（ここが合体のコア）
    k_merged = (1.0 - ratio) * k_a + ratio * k_b
    
    # LPCに戻す
    return parcor_to_lpc(k_merged)

# ==========================================
# 使い方：ここに取得したLPC係数を貼り付けてください
# ==========================================
# 声A（Voice A）
lpc_a_raw = []

# 声B（Voice B）
lpc_b_raw = []

# 比率を指定（0.5なら50%ずつの合体）
blend_ratio = 0.5 

# 合体実行
merged_lpc = merge_lpc(lpc_a_raw, lpc_b_raw, ratio=blend_ratio)

# 出力
print(f"\n--- 合体結果 (比率: {blend_ratio*100}%) ---")
print(", ".join([f"{x:.4f}" for x in merged_lpc]))

# バリエーションをいくつか出すなら
print("\n--- グラデーション（0%〜100%） ---")
for r in [0.25, 0.5, 0.75]:
    m = merge_lpc(lpc_a_raw, lpc_b_raw, ratio=r)
    print(f"比率 {int(r*100):>3}%: {', '.join([f'{x:.4f}' for x in m[:5]])} ... (以下略)")