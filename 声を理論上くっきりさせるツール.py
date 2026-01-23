import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import librosa
import numpy as np
from scipy.io import wavfile
import os
import threading
import queue

# --- 音声処理コア機能（変更なし） ---
def extract_dynamic_f0(y, sr):
    f0, voiced_flag, voiced_probs = librosa.pyin(y, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'))
    nan_mask = np.isnan(f0)
    if np.all(nan_mask):
        raise ValueError("有効な基音が検出されませんでした。")
    f0[nan_mask] = np.interp(np.flatnonzero(nan_mask), np.flatnonzero(~nan_mask), f0[~nan_mask])
    return f0

def filter_harmonics_dynamic(y, sr, f0_dynamic, bandwidth=20):
    stft = librosa.stft(y)
    freqs = librosa.fft_frequencies(sr=sr)
    times = librosa.times_like(stft, sr=sr)
    if len(f0_dynamic) != stft.shape[1]:
        f0_resampled = np.interp(times, librosa.times_like(f0_dynamic), f0_dynamic)
    else:
        f0_resampled = f0_dynamic
    mask = np.zeros_like(stft, dtype=bool)
    valid_f0 = f0_resampled[f0_resampled > 0]
    if len(valid_f0) == 0:
        return np.zeros_like(y)
    min_f0 = np.min(valid_f0)
    max_harmonic = int(sr / 2 / min_f0) if min_f0 > 0 else 1
    
    for t in range(stft.shape[1]):
        f0_t = f0_resampled[t]
        if f0_t <= 0 or np.isnan(f0_t):
            continue
        for n in range(1, max_harmonic + 1):
            harmonic_freq = n * f0_t
            idx = np.where((freqs >= harmonic_freq - bandwidth) & (freqs <= harmonic_freq + bandwidth))[0]
            mask[idx, t] = True
    stft_filtered = stft * mask
    y_filtered = librosa.istft(stft_filtered)
    return y_filtered

def process_audio(input_paths, output_dir, custom_output_name, suffix, overwrite_flag, q):
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
                if messagebox.askyesno("確認", f"出力先ディレクトリが存在しません:\n{effective_output_dir}\n\n新規作成しますか？"):
                    os.makedirs(effective_output_dir)
                else:
                    q.put("処理がキャンセルされました。")
                    q.put(("SHOW_INFO", "キャンセル", "出力ディレクトリの作成がキャンセルされたため、処理を中断しました。"))
                    return

            output_path = os.path.join(effective_output_dir, output_name)
            
            if total_files > 1 and not overwrite_flag and os.path.exists(output_path):
                q.put(f"スキップ (ファイル存在): {os.path.basename(output_path)}")
                skipped_count += 1
                continue

            y, sr = librosa.load(input_path, sr=None)
            f0_dynamic = extract_dynamic_f0(y, sr)
            y_filtered = filter_harmonics_dynamic(y, sr, f0_dynamic)
            
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


# --- GUI関連機能（変更なし） ---
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
        args=(input_paths, output_dir, custom_name, suffix, overwrite_flag, q),
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
root.title("音声フィルタリングツール")
root.geometry("600x600")

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
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★
# 修正点: suffix_entryの初期値を"_cuted"に戻しました
suffix_entry.insert(0, "_cuted")
# ★★★★★★★★★★★★★★★★★★★★★★★★★★★★
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