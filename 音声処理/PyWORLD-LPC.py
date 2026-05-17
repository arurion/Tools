import pyworld as pw
import soundfile as sf
import numpy as np
import librosa
from scipy.linalg import toeplitz, solve

# ====== 設定 ======
wav_path = r"hogehoge"  # 用意する音声ファイル（「あ」など単音の録音がおすすめ）
lpc_order = 32          # LPCの次数（口の形の複雑さ。10〜16程度）

# 1. 音声の読み込み (PyWORLDは float64 型を要求します)
x, fs = librosa.load(wav_path''', sr=16000''')#←srは男声の場合などに有効にすべき
if x.ndim > 1:
    x = x[:, 0]  # ステレオならモノラルに変換
x = x.astype(np.float64)

# 2. PyWORLDによる超高精度な分析
print("PyWORLDで分析中...")
# F0（声の高さ）の抽出
_f0, t = pw.harvest(x, fs)
f0 = pw.stonemask(x, _f0, t, fs) # F0の精度をさらに上げる

# スペクトル包絡（口の形だけの純粋なデータ）の抽出 [CheapTrick]
# これがPyWORLDの真骨頂。声帯の振動成分が完全に除去されたデータが手に入ります。
sp = pw.cheaptrick(x, f0, t, fs)

# 3. WORLDのスペクトル包絡から、LPC係数に変換する
print("スペクトル包絡をLPC係数に変換中...")
lpc_frames =[]

# 各フレーム（数ミリ秒ごと）のデータを処理
for i in range(sp.shape[0]):
    S = sp[i, :] # 1フレーム分のパワースペクトル
    
    # 【魔法の計算 1】パワースペクトルを逆フーリエ変換すると「自己相関関数」になる
    autocorr = np.fft.irfft(S)
    
    # LPCの計算に必要な部分だけ取り出す
    r = autocorr[:lpc_order + 1]
    
    # 【魔法の計算 2】ユール・ウォーカー方程式を解いてLPC係数を導出
    # R_mat * a = -r の連立方程式を行列計算で解く
    R_mat = toeplitz(r[:-1])
    try:
        a = solve(R_mat, -r[1:])
        # LPC係数の先頭には必ず 1.0 が入る
        lpc_coeffs = np.concatenate(([1.0], a))
    except np.linalg.LinAlgError:
        # 万が一計算が破綻した時（無音区間など）の安全装置
        lpc_coeffs = np.zeros(lpc_order + 1)
        lpc_coeffs[0] = 1.0
        
    lpc_frames.append(lpc_coeffs)

lpc_frames = np.array(lpc_frames)

# ====== 結果の確認 ======
# 例として、音声の真ん中あたり（一番声が安定している部分）のLPC係数を表示
mid_frame = len(lpc_frames) // 2
best_lpc = lpc_frames[mid_frame]

print("\n=== 抽出成功！ ===")
print(f"フレーム数: {len(lpc_frames)} フレーム (1フレーム約5ms)")
print(f"一番安定している部分のLPC係数 (a0 〜 a{lpc_order}):")
# ブラウザツールにコピペしやすいようにカンマ区切りで出力 (a1以降)
lpc_csv = ", ".join([f"{val:.4f}" for val in best_lpc[1:]])
print(lpc_csv)

print("\n↑ このカンマ区切りの数値を、先ほどのHTMLツールのテキストエリアに貼り付けると、")
print("PyWORLDが抽出した『あなたの声の口の形』でロボットボイスが鳴ります！")
