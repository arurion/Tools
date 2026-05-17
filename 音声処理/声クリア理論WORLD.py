import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import librosa
import numpy as np
from scipy.io import wavfile
import os
import threading
import queue
import pyworld as pw  # WORLD (Harvest) 用

# --- 音声処理コア機能 ---

def extract_dynamic_f0(y, sr, f_min, f_max):
    """
    WORLDのHarvestを使用してF0を抽出します。
    """
    # WORLDはfloat64を要求するため型変換
    y = y.astype(np.float64)
    
    # HarvestによるF0推定 (frame_periodはデフォルト5.0ms)
    frame_period = 5.0
    f0, t = pw.harvest(y, sr, f0_floor=f_min, f0_ceil=f_max, frame_period=frame_period)
    
    # Harvestは無声音を0で返します。
    # 完全に無効なデータ（全て0など）の場合のチェック
    if np.all(f0 == 0):
        raise ValueError("有効な基音が検出されませんでした。範囲設定を見直してください。")
        
    return f0, t

def filter_harmonics_dynamic(y, sr, f0_dynamic, f0_times, bandwidth=20):
    """
    F0に追従して倍音成分のみを抽出します（時間軸補正付き）。
    """
    stft = librosa.stft(y)
    freqs = librosa.fft_frequencies(sr=sr)
    times = librosa.times_like(stft, sr=sr) # STFT側の時間軸
    
    # WORLDのF0時間軸(f0_times)をSTFTの時間軸(times)に合わせてリサンプリング
    if len(f0_dynamic) != stft.shape[1]:
        f0_resampled = np.interp(times, f0_times, f0_dynamic)
    else:
        f0_resampled = f0_dynamic

    mask = np.zeros_like(stft, dtype=bool)
    
    # 0より大きい有効なF0だけで最小値を計算（高調波の上限計算用）
    valid_f0 = f0_resampled[f0_resampled > 0]
    if len(valid_f0) == 0:
        return np.zeros_like(y)
    
    min_f0 = np.min(valid_f0)
    max_harmonic = int(sr / 2 / min_f0) if min_f0 > 0 else 1
    
    # フレームごとにマスクを作成
    for t_idx in range(stft.shape[1]):
        f0_t = f0_resampled[t_idx]
        
        # WORLDで0（無声音）と判定された箇所はスキップ（マスクしない＝無音化）
        if f0_t <= 0 or np.isnan(f0_t):
            continue
            
        for n in range(1, max_harmonic + 1):
            harmonic_freq = n * f0_t
            # 指定帯域幅内の周波数インデックスを取得
            idx = np.where((freqs >= harmonic_freq - bandwidth) & (freqs <= harmonic_freq + bandwidth))[0]
            mask[idx, t_idx] = True
            
    stft_filtered = stft * mask
    y_filtered = librosa.istft(stft_filtered)
    return y_filtered

def process_audio(input_paths, output_dir, custom_output_name, suffix, overwrite_flag, f_min, f_max, q):
    try:
        total_files = len(input_paths)
        processed_count = 0
        skipped_count = 0

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
                # GUIスレッド外からの呼び出しになるため、メッセージボックスの結果をqueue経由などで受け取るのが理想ですが、
                # 簡易化のためここではディレクトリ強制作成せずエラー終了または作成確認を行います。
                # ただしtkinterのmessageboxはメインスレッド推奨ですが、単純なyesnoは動作することが多いです。
                # 安全のため、事前にチェックするロジックが望ましいですが、元の構造を維持します。
                os.makedirs(effective_output_dir, exist_ok=True) 

            output_path = os.path.join(effective_output_dir, output_name)
            
            if total_files > 1 and not overwrite_flag and os.path.exists(output_path):
                q.put(f"スキップ (ファイル存在): {os.path.basename(output_path)}")
                skipped_count += 1
                continue

            # オーディオ読み込み
            y, sr = librosa.load(input_path, sr=None)
            
            # WORLD HarvestによるF0抽出
            f0_dynamic, f0_times = extract_dynamic_f0(y, sr, f_min, f_max)
            
            # フィルタリング実行
            y_filtered = filter_harmonics_dynamic(y, sr, f0_dynamic, f0_times)
            
            # 書き出し
            wavfile.write(output_path, sr, (y_filtered * 32767).astype(np.int16))
            processed_count += 1

        final_message = f"処理完了 | 成功: {processed_count}件, スキップ: {skipped_count}件"
        q.put(final_message)
        q.put(("SHOW_INFO", "成功", final_message))

    except Exception as e:
        error_message = f"エラーが発生しました: {e}"
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

    # パラメータ取得と検証
    try:
        f_min = float(fmin_entry.get())
        f_max = float(fmax_entry.get())
        if f_min >= f_max:
            messagebox.showerror("エラー", "最小周波数は最大周波数より小さくある必要があります。")
            return
    except ValueError:
        messagebox.showerror("エラー", "周波数設定には数値を入力してください。")
        return

    if len(input_paths) == 1:
        base_name = os.path.splitext(os.path.basename(input_paths[0]))[0]
        if not custom_name:
            output_name = base_name + ".wav"
        else:
            output_name = custom_name if custom_name.endswith('.wav') else custom_name + '.wav'
        
        effective_output_dir = output_dir if output_dir else os.path.dirname(input_paths[0])
        output_path = os.path.join(effective_output_dir, output_name)
        
        if os.path.exists(output_path):
            if not messagebox.askyesno("確認", f"ファイル '{output_name}' は既に存在します。\n上書きしますか？"):
                status_label.config(text="処理がキャンセルされました。")
                return
    
    process_button.config(state=tk.DISABLED)
    threading.Thread(
        target=process_audio,
        args=(input_paths, output_dir, custom_name, suffix, overwrite_flag, f_min, f_max, q),
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
        else:
            status_label.config(text=message)
    except queue.Empty:
        pass
    finally:
        root.after(100, check_queue)

# --- GUIセットアップ ---
root = tk.Tk()
root.title("音声フィルタリングツール (WORLD Harvest版)")
root.geometry("600x700") # 高さを少し拡張

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

# --- パラメータ設定フレーム ---
param_frame = ttk.LabelFrame(main_frame, text="WORLD Harvest 設定")
param_frame.pack(fill=tk.X, pady=5)

# グリッドレイアウトで配置
param_frame.columnconfigure(1, weight=1)
param_frame.columnconfigure(3, weight=1)

ttk.Label(param_frame, text="最小周波数 (Hz):").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
fmin_entry = ttk.Entry(param_frame)
fmin_entry.insert(0, "70") # デフォルト値
fmin_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.EW)

ttk.Label(param_frame, text="最大周波数 (Hz):").grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
fmax_entry = ttk.Entry(param_frame)
fmax_entry.insert(0, "1100") # デフォルト値
fmax_entry.grid(row=0, column=3, padx=5, pady=5, sticky=tk.EW)

# --- 出力設定フレーム ---
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

process_button = ttk.Button(main_frame, text="処理実行 (WORLD Harvest)", state=tk.DISABLED, command=start_processing)
process_button.pack(pady=10, fill=tk.X)

status_label = ttk.Label(main_frame, text="準備完了")
status_label.pack(anchor=tk.W)

update_ui_state()
check_queue()
root.mainloop()
