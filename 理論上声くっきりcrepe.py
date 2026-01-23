import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import librosa
import numpy as np
from scipy.io import wavfile
import os
import threading
import queue
import torch
import torchcrepe

# --- 音声処理コア機能（TorchCrepe版） ---

def extract_f0_crepe(y, sr, model_capacity):
    """
    TorchCrepeを使用してF0を抽出する
    """
    # Crepeは16kHzで動作するため、解析用にリサンプリング
    # 音質劣化を防ぐため、元の y は変更せず、解析用データのみ作る
    target_sr = 16000
    if sr != target_sr:
        y_16k = librosa.resample(y, orig_sr=sr, target_sr=target_sr)
    else:
        y_16k = y

    # Tensor化
    audio = torch.tensor(y_16k).unsqueeze(0)
    
    # デバイス選択 (GPUがあればGPUを使用)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    audio = audio.to(device)

    # Crepeのホップ長 (10ms = 160 samples @ 16kHz)
    hop_length_crepe = 160

    # F0予測
    # batch_sizeはVRAMに合わせて調整可能ですが、2048あたりが安全です
    f0, confidence = torchcrepe.predict(
        audio,
        sr=target_sr,
        hop_length=hop_length_crepe,
        fmin=librosa.note_to_hz('C2'),
        fmax=librosa.note_to_hz('C7'),
        model=model_capacity,
        batch_size=2048,
        device=device,
        decoder=torchcrepe.decode.viterbi
    )
    
    # GPUからCPUへ戻し、numpy配列化
    f0 = f0.squeeze(0).cpu().numpy()
    
    # 時間軸の生成 (秒)
    # Crepeの出力フレーム数に対応する時間軸
    times_crepe = np.arange(len(f0)) * hop_length_crepe / target_sr
    
    return f0, times_crepe

def filter_harmonics_dynamic(y, sr, f0_crepe, times_crepe, bandwidth=20):
    stft = librosa.stft(y)
    freqs = librosa.fft_frequencies(sr=sr)
    times_stft = librosa.times_like(stft, sr=sr)
    
    # STFTの時間軸に合わせてF0を線形補間
    # Crepeの時間軸(times_crepe) -> STFTの時間軸(times_stft)
    f0_resampled = np.interp(times_stft, times_crepe, f0_crepe)
    
    # F0がNaNの部分を補間（念のため）
    nan_mask = np.isnan(f0_resampled)
    if np.any(nan_mask):
        # 全てNaNでない場合のみ補間
        if not np.all(nan_mask):
            f0_resampled[nan_mask] = np.interp(
                np.flatnonzero(nan_mask), 
                np.flatnonzero(~nan_mask), 
                f0_resampled[~nan_mask]
            )
        else:
            return np.zeros_like(y) # 全て無声/検出なしなら無音

    mask = np.zeros_like(stft, dtype=bool)
    
    # 有効なF0の最小値を計算（高調波上限計算用）
    valid_f0 = f0_resampled[f0_resampled > 0]
    if len(valid_f0) == 0:
        return np.zeros_like(y)
    
    min_f0 = np.min(valid_f0)
    # 0除算防止
    if min_f0 <= 0: min_f0 = 1 
    
    max_harmonic = int(sr / 2 / min_f0)
    
    # ベクトル化は難しいので時間フレームごとに処理
    # (ここを高速化するにはnumpyのブロードキャストを工夫する必要がありますが、今回はロジック維持)
    for t in range(stft.shape[1]):
        f0_t = f0_resampled[t]
        if f0_t <= 0 or np.isnan(f0_t):
            continue
        
        # 基本周波数〜最高次倍音までループ
        # max_harmonicが大きすぎると重くなるため、実用的な範囲（例: 20kHzまで）で回すのが一般的ですが
        # 元のロジックに従い計算します。
        current_max_h = int(sr / 2 / f0_t)
        
        for n in range(1, current_max_h + 1):
            harmonic_freq = n * f0_t
            # 周波数インデックスの抽出（帯域幅内）
            idx = np.where((freqs >= harmonic_freq - bandwidth) & (freqs <= harmonic_freq + bandwidth))[0]
            mask[idx, t] = True
            
    stft_filtered = stft * mask
    y_filtered = librosa.istft(stft_filtered)
    
    # 元の長さと合わせる（istftで微妙にずれることがあるため）
    if len(y_filtered) > len(y):
        y_filtered = y_filtered[:len(y)]
    elif len(y_filtered) < len(y):
        y_filtered = np.pad(y_filtered, (0, len(y) - len(y_filtered)))
        
    return y_filtered

def process_audio(input_paths, output_dir, custom_output_name, suffix, overwrite_flag, model_capacity, q):
    try:
        total_files = len(input_paths)
        processed_count = 0
        skipped_count = 0
        
        # デバイス情報のログ出力
        device = 'CUDA (GPU)' if torch.cuda.is_available() else 'CPU'
        q.put(f"処理デバイス: {device} | モデル: {model_capacity}")

        for i, input_path in enumerate(input_paths):
            q.put(f"処理中: {os.path.basename(input_path)} ({i+1}/{total_files})")
            
            base_name = os.path.splitext(os.path.basename(input_path))[0]
            
            if total_files == 1:
                if not custom_output_name:
                    output_name = base_name + ".wav"
                else:
                    output_name = custom_output_name if custom_output_name.endswith('.wav') else custom_output_name + '.wav'
                effective_output_dir = output_dir if output_dir else os.path.dirname(input_path)
            else: 
                output_name = base_name + (suffix if not suffix.endswith('.wav') else suffix.replace('.wav', '')) + ".wav"
                effective_output_dir = output_dir if output_dir else os.path.dirname(input_path)

            if not os.path.exists(effective_output_dir):
                # GUIスレッドではないため、本来は直接askyesnoできないが、
                # 簡易実装として例外的にここでの処理は省略し、事前にフォルダ作成確認を済ませている前提とするか、
                # 自動作成とする。今回は「なければ作る」挙動にします（元コードの対話部分はスレッド内だとフリーズの原因になるため）
                os.makedirs(effective_output_dir, exist_ok=True)

            output_path = os.path.join(effective_output_dir, output_name)
            
            if total_files > 1 and not overwrite_flag and os.path.exists(output_path):
                q.put(f"スキップ (ファイル存在): {os.path.basename(output_path)}")
                skipped_count += 1
                continue

            # 音声ロード
            y, sr = librosa.load(input_path, sr=None)
            
            # F0抽出 (TorchCrepe)
            try:
                f0_crepe, times_crepe = extract_f0_crepe(y, sr, model_capacity)
                
                # 高調波フィルタリング
                y_filtered = filter_harmonics_dynamic(y, sr, f0_crepe, times_crepe)
                
                # 保存
                wavfile.write(output_path, sr, (y_filtered * 32767).astype(np.int16))
                processed_count += 1
            except Exception as e:
                q.put(f"ファイル処理エラー ({os.path.basename(input_path)}): {str(e)}")
                # 個別のエラーは続行

        final_message = f"処理完了 | 成功: {processed_count}件, スキップ: {skipped_count}件"
        q.put(final_message)
        q.put(("SHOW_INFO", "成功", final_message))

    except Exception as e:
        error_message = f"全体エラーが発生しました: {e}"
        q.put(error_message)
        q.put(("SHOW_ERROR", "エラー", error_message))
    finally:
        q.put("PROCESS_COMPLETE")


# --- GUI関連機能 ---
def select_files():
    file_paths = filedialog.askopenfilenames(filetypes=[("WAV files", "*.wav")])
    if file_paths:
        update_file_list(file_paths)
        update_ui_state()

def update_file_list(file_paths):
    file_listbox.delete(0, tk.END)
    for path in file_paths:
        file_listbox.insert(tk.END, path)

def clear_file_list():
    file_listbox.delete(0, tk.END)
    update_ui_state()
    
def update_ui_state():
    num_files = file_listbox.size()
    summary_var.set(f"{num_files} 個のファイルが選択されています。")

    if num_files == 0:
        process_button.config(state=tk.DISABLED)
    else:
        process_button.config(state=tk.NORMAL)

    if num_files > 1:
        output_name_entry.config(state=tk.DISABLED)
        suffix_entry.config(state=tk.NORMAL)
        overwrite_checkbutton.config(state=tk.NORMAL)
    else:
        output_name_entry.config(state=tk.NORMAL if num_files == 1 else tk.DISABLED)
        suffix_entry.config(state=tk.DISABLED)
        overwrite_checkbutton.config(state=tk.DISABLED)

def get_input_paths():
    return list(file_listbox.get(0, tk.END))

def select_output_dir():
    dir_path = filedialog.askdirectory()
    if dir_path:
        output_dir_entry.delete(0, tk.END)
        output_dir_entry.insert(0, dir_path)

def start_processing():
    input_paths = get_input_paths()
    if not input_paths:
        messagebox.showerror("エラー", "入力ファイルが指定されていません。")
        return

    output_dir = output_dir_entry.get().strip()
    custom_name = output_name_entry.get().strip()
    suffix = suffix_entry.get().strip()
    overwrite_flag = overwrite_var.get()
    model_capacity = model_var.get() # モデルサイズの取得

    # 単一ファイルの事前確認
    if len(input_paths) == 1:
        base_name = os.path.splitext(os.path.basename(input_paths[0]))[0]
        if not custom_name:
            output_name = base_name + ".wav"
        else:
            output_name = custom_name if custom_name.endswith('.wav') else custom_name + '.wav'
        
        effective_output_dir = output_dir if output_dir else os.path.dirname(input_paths[0])
        output_path = os.path.join(effective_output_dir, output_name)
        
        # 出力先ディレクトリの確認（スレッド開始前に確認できるものはここで）
        if not os.path.exists(effective_output_dir):
            if messagebox.askyesno("確認", f"出力先ディレクトリが存在しません:\n{effective_output_dir}\n\n新規作成しますか？"):
                os.makedirs(effective_output_dir, exist_ok=True)
            else:
                status_label.config(text="処理がキャンセルされました。")
                return

        if os.path.exists(output_path):
            if not messagebox.askyesno("確認", f"ファイル '{output_name}' は既に存在します。\n上書きしますか？"):
                status_label.config(text="処理がキャンセルされました。")
                return
    else:
        # 複数ファイルの場合のディレクトリチェック
        effective_output_dir = output_dir if output_dir else os.path.dirname(input_paths[0])
        if not os.path.exists(effective_output_dir):
             if messagebox.askyesno("確認", f"出力先ディレクトリが存在しません:\n{effective_output_dir}\n\n新規作成しますか？"):
                os.makedirs(effective_output_dir, exist_ok=True)
             else:
                status_label.config(text="処理がキャンセルされました。")
                return
    
    process_button.config(state=tk.DISABLED)
    status_label.config(text="TorchCrepeを初期化中...")
    
    threading.Thread(
        target=process_audio,
        args=(input_paths, output_dir, custom_name, suffix, overwrite_flag, model_capacity, q),
        daemon=True
    ).start()

def check_queue():
    try:
        message = q.get_nowait()
        if isinstance(message, tuple):
            msg_type, title, text = message
            if msg_type == "SHOW_INFO":
                messagebox.showinfo(title, text)
            elif msg_type == "SHOW_ERROR":
                messagebox.showerror(title, text)
        elif message == "PROCESS_COMPLETE":
            process_button.config(state=tk.NORMAL)
            status_label.config(text="待機中")
        else:
            status_label.config(text=message)
    except queue.Empty:
        pass
    finally:
        root.after(100, check_queue)

# --- GUIセットアップ ---
root = tk.Tk()
root.title("音声フィルタリングツール (TorchCrepe版)")
root.geometry("600x680") # 少し縦長に

q = queue.Queue()

main_frame = ttk.Frame(root, padding="10")
main_frame.pack(fill=tk.BOTH, expand=True)

input_frame = ttk.LabelFrame(main_frame, text="入力ファイル")
input_frame.pack(fill=tk.X, pady=5)

summary_var = tk.StringVar()
summary_entry = ttk.Entry(input_frame, textvariable=summary_var, state='readonly')
summary_entry.pack(fill=tk.X, expand=True, padx=5, pady=2)

button_frame = ttk.Frame(input_frame)
button_frame.pack(fill=tk.X, pady=5)
ttk.Button(button_frame, text="ファイルを選択...", command=select_files).pack(side=tk.LEFT, padx=5)
ttk.Button(button_frame, text="リストをクリア", command=clear_file_list).pack(side=tk.LEFT, padx=5)

list_frame = ttk.LabelFrame(main_frame, text="選択ファイルリスト (フルパス)")
list_frame.pack(fill=tk.BOTH, expand=True, pady=5)

listbox_container = ttk.Frame(list_frame)
listbox_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

file_listbox = tk.Listbox(listbox_container, selectmode=tk.EXTENDED)
file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

v_scrollbar = ttk.Scrollbar(listbox_container, orient=tk.VERTICAL, command=file_listbox.yview)
v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
h_scrollbar = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=file_listbox.xview)
h_scrollbar.pack(fill=tk.X, padx=5)
file_listbox.config(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)

# --- 設定フレーム (Crepeモデル選択) ---
settings_frame = ttk.LabelFrame(main_frame, text="解析設定")
settings_frame.pack(fill=tk.X, pady=5)

ttk.Label(settings_frame, text="TorchCrepe モデルサイズ:").pack(side=tk.LEFT, padx=5)
model_var = tk.StringVar(value="full")
model_combo = ttk.Combobox(settings_frame, textvariable=model_var, state="readonly", width=10)
model_combo['values'] = ('tiny', 'small', 'medium', 'large', 'full')
model_combo.pack(side=tk.LEFT, padx=5)
ttk.Label(settings_frame, text="(大きいほど高精度ですが遅くなります)").pack(side=tk.LEFT, padx=5)
# ------------------------------------

output_frame = ttk.LabelFrame(main_frame, text="出力設定")
output_frame.pack(fill=tk.X, pady=5)

ttk.Label(output_frame, text="出力ディレクトリ (空欄の場合は入力元と同じ場所):").pack(anchor=tk.W, padx=5)
output_dir_entry = ttk.Entry(output_frame)
output_dir_entry.pack(fill=tk.X, expand=True, padx=5, pady=2)
ttk.Button(output_frame, text="ディレクトリ選択...", command=select_output_dir).pack(pady=5)

ttk.Label(output_frame, text="出力ファイル名 (単一ファイル時、空欄で同名):").pack(anchor=tk.W, padx=5)
output_name_entry = ttk.Entry(output_frame, state=tk.DISABLED)
output_name_entry.pack(fill=tk.X, padx=5, pady=2)

ttk.Label(output_frame, text="接尾辞 (一括処理時、空欄で接尾辞なし):").pack(anchor=tk.W, padx=5)
suffix_entry = ttk.Entry(output_frame)
suffix_entry.insert(0, "_cuted")
suffix_entry.pack(fill=tk.X, padx=5, pady=2)

overwrite_var = tk.BooleanVar(value=False)
overwrite_checkbutton = ttk.Checkbutton(output_frame, text="既存のファイルを上書きする (一括処理時)", variable=overwrite_var, state=tk.DISABLED)
overwrite_checkbutton.pack(anchor=tk.W, padx=5, pady=5)

process_button = ttk.Button(main_frame, text="処理実行", state=tk.DISABLED, command=start_processing)
process_button.pack(pady=10, fill=tk.X)

status_label = ttk.Label(main_frame, text="準備完了")
status_label.pack(anchor=tk.W)

update_ui_state()
check_queue()
root.mainloop()