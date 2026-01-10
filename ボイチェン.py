import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import librosa
import numpy as np
from scipy.io import wavfile
import os
import threading
import queue
import glob
import torch
import torchcrepe
import pyworld as pw

# --- バックエンド処理 ---

def get_standardized_f0(y, sr, method, model_capacity, threshold, f0_min, f0_max):
    """
    指定されたアルゴリズムと範囲設定でF0を抽出し、
    WORLD処理用の厳密な時間軸(5ms周期)に統一して返す
    """
    frame_period = 5.0
    n_frames = int(len(y) / (sr * frame_period / 1000.0)) + 1
    t_target = np.arange(n_frames) * frame_period / 1000.0
    
    f0_standard = None
    
    # --- A. TorchCrepe ---
    if method == "crepe":
        target_sr = 16000
        y_32 = y.astype(np.float32)

        if sr != target_sr:
            y_16k = librosa.resample(y_32, orig_sr=sr, target_sr=target_sr)
        else:
            y_16k = y_32
            
        audio = torch.tensor(y_16k, dtype=torch.float32).unsqueeze(0)
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        audio = audio.to(device)
        
        hop_length = 160 # 10ms @ 16k
        batch_size = 2048

        f0, confidence = torchcrepe.predict(
            audio,
            sample_rate=target_sr,
            hop_length=hop_length,
            fmin=f0_min,
            fmax=f0_max,
            model=model_capacity,
            batch_size=batch_size,
            device=device,
            return_periodicity=True,
            decoder=torchcrepe.decode.viterbi
        )
        f0 = f0.squeeze(0).cpu().numpy()
        confidence = confidence.squeeze(0).cpu().numpy()
        times_crepe = np.arange(len(f0)) * hop_length / target_sr
        
        f0_interp = np.interp(t_target, times_crepe, f0)
        conf_interp = np.interp(t_target, times_crepe, confidence)
        
        f0_interp[conf_interp < threshold] = 0
        f0_standard = f0_interp

    # --- B. WORLD (Harvest) ---
    elif method == "harvest":
        y_64 = y.astype(np.float64)
        _f0, t = pw.harvest(y_64, sr, frame_period=frame_period, f0_floor=f0_min, f0_ceil=f0_max)
        f0_refined = pw.stonemask(y_64, _f0, t, sr)
        f0_standard = np.interp(t_target, t, f0_refined)

    # --- C. WORLD (Dio) ---
    elif method == "dio":
        y_64 = y.astype(np.float64)
        _f0, t = pw.dio(y_64, sr, frame_period=frame_period, f0_floor=f0_min, f0_ceil=f0_max)
        f0_refined = pw.stonemask(y_64, _f0, t, sr)
        f0_standard = np.interp(t_target, t, f0_refined)

    # --- D. librosa.pyin ---
    elif method == "pyin":
        f0, voiced_flag, voiced_probs = librosa.pyin(
            y, 
            fmin=f0_min, 
            fmax=f0_max,
            sr=sr,
            frame_length=2048
        )
        times_pyin = librosa.times_like(f0, sr=sr)
        f0 = np.nan_to_num(f0)
        f0_interp = np.interp(t_target, times_pyin, f0)
        f0_standard = f0_interp

    return f0_standard, t_target

def process_with_world_and_eq(y, sr, f0, t_world, semitones, eq_rules, residual_gain_db):
    y = np.ascontiguousarray(y, dtype=np.float64)
    f0 = np.ascontiguousarray(f0, dtype=np.float64)
    
    sp = pw.cheaptrick(y, f0, t_world, sr)
    ap = pw.d4c(y, f0, t_world, sr)
    
    if semitones != 0:
        pitch_scale = 2.0 ** (semitones / 12.0)
        f0_shifted = f0 * pitch_scale
    else:
        f0_shifted = f0

    y_synthesized = pw.synthesize(f0_shifted, sp, ap, sr, frame_period=5.0)
    
    # 合成時の長さズレ補正
    if len(y_synthesized) != len(y):
        min_len = min(len(y), len(y_synthesized))
        y_synthesized = y_synthesized[:min_len]
        if len(y_synthesized) < len(y):
            y_synthesized = np.pad(y_synthesized, (0, len(y) - len(y_synthesized)))

    if eq_rules or residual_gain_db != 0:
        y_final = apply_harmonic_eq_stft(y_synthesized, sr, f0_shifted, t_world, eq_rules, residual_gain_db)
    else:
        y_final = y_synthesized

    return y_final

def apply_harmonic_eq_stft(y, sr, f0, times, eq_rules, residual_gain_db, bandwidth=25):
    # FFT設定 (明示的に指定)
    n_fft = 2048
    hop_length = n_fft // 4
    
    stft = librosa.stft(y, n_fft=n_fft, hop_length=hop_length)
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    times_stft = librosa.times_like(stft, sr=sr, hop_length=hop_length)
    mag = np.abs(stft)
    
    f0_resampled = np.interp(times_stft, times, f0)
    
    residual_gain_linear = 10 ** (residual_gain_db / 20.0)
    gain_mask = np.full_like(stft, residual_gain_linear, dtype=np.float32)

    # 窓関数(Hann)による減衰を考慮した補正係数 (簡易近似: n_fft/2)
    # 時間領域の振幅1.0 は、STFTスペクトル上では n_fft/2 程度の値になる
    stft_scale_factor = n_fft / 2.0

    for h_num, rule in eq_rules.items():
        h_num = float(h_num)
        mode = rule['type']
        val_db = rule['value']

        harmonic_indices_map = np.zeros_like(stft, dtype=bool)

        for t in range(stft.shape[1]):
            if f0_resampled[t] <= 0: continue
            
            target_freq = h_num * f0_resampled[t]
            idx = np.where((freqs >= target_freq - bandwidth) & (freqs <= target_freq + bandwidth))[0]
            harmonic_indices_map[idx, t] = True
        
        if mode == 'relative':
            # 相対ゲイン: 単純な掛け算
            target_gain = 10 ** (val_db / 20.0)
            gain_mask[harmonic_indices_map] = target_gain
            
        elif mode == 'target':
            # 目標ピーク(dBFS): スペクトル値とのスケール合わせが必要
            current_harmonic_mag = mag[harmonic_indices_map]
            current_peak = np.max(current_harmonic_mag) if current_harmonic_mag.size > 0 else 0
            
            if current_peak > 1e-6:
                target_amp_linear = 10 ** (val_db / 20.0) # 時間領域での目標振幅 (0~1.0)
                
                # ★修正ポイント: スペクトル領域での目標値に変換
                target_mag_stft = target_amp_linear * stft_scale_factor
                
                scaling_factor = target_mag_stft / current_peak
                gain_mask[harmonic_indices_map] = scaling_factor
            else:
                gain_mask[harmonic_indices_map] = 0

    stft_filtered = stft * gain_mask
    y_filtered = librosa.istft(stft_filtered, n_fft=n_fft, hop_length=hop_length)
    
    if len(y_filtered) > len(y):
        y_filtered = y_filtered[:len(y)]
    elif len(y_filtered) < len(y):
        y_filtered = np.pad(y_filtered, (0, len(y) - len(y_filtered)))
        
    return y_filtered

def processing_thread(input_paths, output_dir, custom_output_name, suffix, overwrite, 
                      detect_method, model_cap, eq_rules, residual_gain, threshold, pitch_semitones, 
                      f0_min, f0_max, is_folder_mode, q):
    try:
        total_files = len(input_paths)
        processed_count = 0
        skipped_count = 0
        error_count = 0
        errors = []

        device = 'CUDA' if torch.cuda.is_available() and detect_method == "crepe" else 'CPU'
        q.put(f"手法: {detect_method} | 範囲: {f0_min}-{f0_max}Hz | デバイス: {device}")
        q.put(("INIT_PROGRESS", total_files))

        for i, input_path in enumerate(input_paths):
            fname = os.path.basename(input_path)
            try:
                q.put(f"処理中 ({i+1}/{total_files}): {fname}")
                base_name = os.path.splitext(fname)[0]
                sfx = suffix.replace('.wav', '') if suffix else ""
                
                if is_folder_mode:
                    target_dir = os.path.join(output_dir if output_dir else os.path.dirname(input_path), "processed_output")
                    os.makedirs(target_dir, exist_ok=True)
                    out_fname = f"{base_name}{sfx}.wav"
                    output_path = os.path.join(target_dir, out_fname)
                else:
                    effective_output_dir = output_dir if output_dir else os.path.dirname(input_path)
                    os.makedirs(effective_output_dir, exist_ok=True)
                    if total_files == 1 and custom_output_name:
                        out_fname = custom_output_name
                    else:
                        out_fname = f"{base_name}{sfx}"
                    if not out_fname.endswith('.wav'): out_fname += '.wav'
                    output_path = os.path.join(effective_output_dir, out_fname)

                if not overwrite and os.path.exists(output_path):
                    q.put(f"スキップ: {os.path.basename(output_path)}")
                    skipped_count += 1
                    q.put(("UPDATE_PROGRESS", 1))
                    continue

                y, sr = librosa.load(input_path, sr=None)
                y = y.astype(np.float64)

                q.put(f"  > F0解析 ({detect_method})...")
                f0_std, t_std = get_standardized_f0(y, sr, detect_method, model_cap, threshold, f0_min, f0_max)
                
                q.put(f"  > 音声再合成 & EQ処理...")
                y_processed = process_with_world_and_eq(y, sr, f0_std, t_std, pitch_semitones, eq_rules, residual_gain)
                
                max_amp = np.max(np.abs(y_processed))
                if max_amp > 1.0:
                    y_processed /= max_amp
                
                wavfile.write(output_path, sr, (y_processed * 32767).astype(np.int16))
                processed_count += 1
                
            except Exception as e:
                error_count += 1
                err_msg = f"エラー ({fname}): {str(e)}"
                errors.append(err_msg)
                q.put(err_msg)
                print(e)
            finally:
                q.put(("UPDATE_PROGRESS", 1))

        summary = f"完了 | 成功: {processed_count}, スキップ: {skipped_count}, エラー: {error_count}"
        q.put(summary)
        
        if errors:
            q.put(("SHOW_WARNING", "完了 (エラーあり)", f"{summary}\n\n主なエラー:\n" + "\n".join(errors[:3])))
        else:
            q.put(("SHOW_INFO", "完了", summary))

    except Exception as e:
        q.put(("SHOW_ERROR", "致命的エラー", str(e)))
    finally:
        q.put("PROCESS_COMPLETE")


# --- GUI クラス ---

class VoiceChangerEQApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Multi-Algorithm Voice Changer & EQ")
        self.root.geometry("700x1000")
        
        self.q = queue.Queue()
        self.is_folder_mode = False

        self._setup_ui()
        self._check_queue()

    def _setup_ui(self):
        main_container = ttk.Frame(self.root)
        main_container.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(main_container)
        scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=self.canvas.yview)
        
        self.scrollable_frame = ttk.Frame(self.canvas)
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas_frame_id = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self.canvas_frame_id, width=e.width))
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.root.bind_all("<MouseWheel>", self._on_mousewheel)

        content_frame = ttk.Frame(self.scrollable_frame, padding="10")
        content_frame.pack(fill=tk.BOTH, expand=True)
        
        # --- 1. 入力 ---
        input_frame = ttk.LabelFrame(content_frame, text="1. 入力ファイル / フォルダ")
        input_frame.pack(fill=tk.X, pady=5)

        self.summary_var = tk.StringVar()
        ttk.Entry(input_frame, textvariable=self.summary_var, state='readonly').pack(fill=tk.X, padx=5, pady=2)

        btn_frame = ttk.Frame(input_frame)
        btn_frame.pack(fill=tk.X, pady=2)
        ttk.Button(btn_frame, text="ファイルを選択", command=self._select_files).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="フォルダを選択 (一括)", command=self._open_directory).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="クリア", command=self._clear_list).pack(side=tk.LEFT, padx=5)

        list_frame = ttk.LabelFrame(input_frame, text="リスト")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.file_listbox = tk.Listbox(list_frame, height=4, selectmode=tk.EXTENDED)
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.file_listbox.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_listbox.config(yscrollcommand=sb.set)

        # --- 2. F0解析設定 ---
        settings_frame = ttk.LabelFrame(content_frame, text="2. F0検出・アルゴリズム設定")
        settings_frame.pack(fill=tk.X, pady=5)

        f_method = ttk.Frame(settings_frame)
        f_method.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(f_method, text="検出方法:").pack(side=tk.LEFT)
        self.method_var = tk.StringVar(value="crepe")
        self.method_combo = ttk.Combobox(f_method, textvariable=self.method_var, state="readonly", width=25)
        self.method_combo['values'] = ('TorchCrepe (高精度・要GPU推奨)', 'WORLD (Harvest) (高精度・低速)', 'WORLD (Dio) (高速・安定)', 'librosa.pyin (従来)')
        self.method_combo.current(0)
        self.method_combo.pack(side=tk.LEFT, padx=5)
        self.method_combo.bind("<<ComboboxSelected>>", self._on_method_change)

        f_range = ttk.Frame(settings_frame)
        f_range.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(f_range, text="F0範囲 (Hz):").pack(side=tk.LEFT)
        self.f0_min_var = tk.DoubleVar(value=50.0)
        ttk.Spinbox(f_range, textvariable=self.f0_min_var, from_=30, to=1000, increment=10, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Label(f_range, text="~").pack(side=tk.LEFT)
        self.f0_max_var = tk.DoubleVar(value=1100.0)
        ttk.Spinbox(f_range, textvariable=self.f0_max_var, from_=200, to=4000, increment=50, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Label(f_range, text="(全アルゴリズムに適用)").pack(side=tk.LEFT, padx=5)

        self.f_model = ttk.Frame(settings_frame)
        self.f_model.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(self.f_model, text="Crepeモデル:").pack(side=tk.LEFT)
        self.model_var = tk.StringVar(value="full")
        self.model_combo = ttk.Combobox(self.f_model, textvariable=self.model_var, values=('tiny', 'small', 'medium', 'large', 'full'), state="readonly", width=10)
        self.model_combo.pack(side=tk.LEFT, padx=5)
        
        f_thresh = ttk.Frame(settings_frame)
        f_thresh.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(f_thresh, text="検出閾値 (Crepe用):").pack(side=tk.LEFT)
        self.thresh_val = tk.DoubleVar(value=0.2)
        self.thresh_scale = ttk.Scale(f_thresh, from_=0.0, to=0.9, variable=self.thresh_val, orient=tk.HORIZONTAL, length=150)
        self.thresh_scale.pack(side=tk.LEFT, padx=5)
        self.thresh_label = ttk.Label(f_thresh, text="0.20")
        self.thresh_label.pack(side=tk.LEFT, padx=5)
        self.thresh_val.trace_add("write", lambda *args: self.thresh_label.config(text=f"{self.thresh_val.get():.2f}"))

        # --- 3. ピッチシフト ---
        pitch_frame = ttk.LabelFrame(content_frame, text="3. ピッチシフト (WORLD)")
        pitch_frame.pack(fill=tk.X, pady=5)
        
        f_pitch = ttk.Frame(pitch_frame)
        f_pitch.pack(fill=tk.X, padx=5, pady=10)
        ttk.Label(f_pitch, text="シフト量 (半音):").pack(side=tk.LEFT)
        self.pitch_val = tk.DoubleVar(value=0.0)
        self.pitch_spin = ttk.Spinbox(f_pitch, from_=-24.0, to=24.0, increment=1.0, textvariable=self.pitch_val, width=6)
        self.pitch_spin.pack(side=tk.LEFT, padx=5)
        ttk.Label(f_pitch, text="( -12=1オクターブ下, +12=1オクターブ上 )").pack(side=tk.LEFT, padx=10)
        ttk.Button(f_pitch, text="リセット", command=lambda: self.pitch_val.set(0.0)).pack(side=tk.RIGHT, padx=5)

        # --- 4. EQ設定 ---
        eq_frame = ttk.LabelFrame(content_frame, text="4. 倍音EQ設定")
        eq_frame.pack(fill=tk.BOTH, expand=True, pady=5)

        input_grid = ttk.Frame(eq_frame)
        input_grid.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(input_grid, text="倍音番号:").grid(row=0, column=0, sticky=tk.W)
        self.spin_h_num = ttk.Spinbox(input_grid, from_=0.1, to=100.0, increment=1.0, width=5)
        self.spin_h_num.set(1.0)
        self.spin_h_num.grid(row=0, column=1, padx=5)
        ttk.Label(input_grid, text="値 (dB):").grid(row=0, column=2, sticky=tk.W)
        self.entry_val = ttk.Entry(input_grid, width=8)
        self.entry_val.insert(0, "-6.0")
        self.entry_val.grid(row=0, column=3, padx=5)
        self.target_mode_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(input_grid, text="目標ピーク(dBFS)モード", variable=self.target_mode_var).grid(row=1, column=0, columnspan=4, sticky=tk.W)
        btn_action = ttk.Frame(input_grid)
        btn_action.grid(row=0, column=4, rowspan=2, padx=10)
        ttk.Button(btn_action, text="追加/更新", command=self._add_rule).pack(fill=tk.X, pady=1)
        ttk.Button(btn_action, text="+ 次の倍音", command=self._add_next_harmonic).pack(fill=tk.X, pady=1)

        columns = ('h_num', 'mode', 'val')
        self.tree = ttk.Treeview(eq_frame, columns=columns, show='headings', height=4)
        self.tree.heading('h_num', text='倍音番号')
        self.tree.column('h_num', width=80, anchor='center')
        self.tree.heading('mode', text='モード')
        self.tree.column('mode', width=150, anchor='center')
        self.tree.heading('val', text='値 (dB)')
        self.tree.column('val', width=80, anchor='center')
        self.tree.pack(fill=tk.X, padx=5)
        ttk.Button(eq_frame, text="選択削除", command=self._delete_rule).pack(anchor=tk.E, padx=5, pady=2)

        res_frame = ttk.Frame(eq_frame)
        res_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(res_frame, text="その他(Residual) ゲイン:").pack(side=tk.LEFT)
        self.res_scale = tk.Scale(res_frame, from_=-60, to=12, orient=tk.HORIZONTAL, resolution=0.1, length=250)
        self.res_scale.set(0)
        self.res_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        # --- 5. 出力 ---
        out_frame = ttk.LabelFrame(content_frame, text="5. 出力設定")
        out_frame.pack(fill=tk.X, pady=5)
        f_out1 = ttk.Frame(out_frame)
        f_out1.pack(fill=tk.X, padx=5)
        ttk.Label(f_out1, text="出力フォルダ:").pack(side=tk.LEFT)
        self.entry_out_dir = ttk.Entry(f_out1)
        self.entry_out_dir.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(f_out1, text="参照", command=self._select_out_dir).pack(side=tk.LEFT)
        f_out2 = ttk.Frame(out_frame)
        f_out2.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(f_out2, text="ファイル名(単一):").pack(side=tk.LEFT)
        self.entry_out_name = ttk.Entry(f_out2)
        self.entry_out_name.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        f_out3 = ttk.Frame(out_frame)
        f_out3.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(f_out3, text="接尾辞:").pack(side=tk.LEFT)
        self.entry_suffix = ttk.Entry(f_out3, width=10)
        self.entry_suffix.insert(0, "_mod")
        self.entry_suffix.pack(side=tk.LEFT, padx=5)
        self.overwrite_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(out_frame, text="上書き許可", variable=self.overwrite_var).pack(side=tk.LEFT, padx=10)

        # --- アクション ---
        action_frame = ttk.Frame(content_frame)
        action_frame.pack(fill=tk.X, pady=10)
        self.progress = ttk.Progressbar(action_frame, mode='determinate')
        self.progress.pack(fill=tk.X, pady=5)
        self.btn_process = ttk.Button(action_frame, text="処理実行", command=self._start_processing, state=tk.DISABLED)
        self.btn_process.pack(fill=tk.X, ipady=5)
        self.lbl_status = ttk.Label(action_frame, text="待機中")
        self.lbl_status.pack(anchor=tk.W, pady=5)

    def _on_mousewheel(self, event):
        if self.canvas.bbox("all")[3] > self.canvas.winfo_height():
            self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")

    def _on_method_change(self, event):
        val = self.method_combo.get()
        if "Crepe" in val:
            self.model_combo.config(state="readonly")
        else:
            self.model_combo.config(state="disabled")

    def _select_files(self):
        paths = filedialog.askopenfilenames(filetypes=[("WAV files", "*.wav")])
        if paths:
            self.file_listbox.delete(0, tk.END)
            for p in paths: self.file_listbox.insert(tk.END, p)
            self.is_folder_mode = False
            self._update_ui_state()

    def _open_directory(self):
        d = filedialog.askdirectory()
        if d:
            self.file_listbox.delete(0, tk.END)
            wavs = glob.glob(os.path.join(d, "*.wav"))
            for p in wavs: self.file_listbox.insert(tk.END, p)
            if not wavs: messagebox.showinfo("情報", "WAVファイルが見つかりませんでした。")
            self.is_folder_mode = True
            self._update_ui_state()

    def _clear_list(self):
        self.file_listbox.delete(0, tk.END)
        self._update_ui_state()

    def _update_ui_state(self):
        cnt = self.file_listbox.size()
        self.summary_var.set(f"{cnt} ファイル選択中")
        self.btn_process.config(state=tk.NORMAL if cnt > 0 else tk.DISABLED)

    def _select_out_dir(self):
        d = filedialog.askdirectory()
        if d:
            self.entry_out_dir.delete(0, tk.END)
            self.entry_out_dir.insert(0, d)

    def _add_rule(self):
        try:
            h_num = float(self.spin_h_num.get())
            val = float(self.entry_val.get())
        except: return
        mode_str = "目標ピーク(dBFS)" if self.target_mode_var.get() else "相対ゲイン(dB)"
        found = False
        for item in self.tree.get_children():
            if float(self.tree.item(item)['values'][0]) == h_num:
                self.tree.item(item, values=(h_num, mode_str, val))
                found = True; break
        if not found: self.tree.insert("", tk.END, values=(h_num, mode_str, val))

    def _add_next_harmonic(self):
        max_h = 0.0
        for item in self.tree.get_children():
            h = float(self.tree.item(item)['values'][0])
            if h > max_h: max_h = h
        self.spin_h_num.set(max_h + 1.0 if max_h > 0 else 1.0)
        self._add_rule()

    def _delete_rule(self):
        for item in self.tree.selection(): self.tree.delete(item)

    def _get_rules(self):
        rules = {}
        for item in self.tree.get_children():
            vals = self.tree.item(item)['values']
            h_num = float(vals[0])
            rules[h_num] = {'type': 'target' if "目標" in vals[1] else 'relative', 'value': float(vals[2])}
        return rules

    def _start_processing(self):
        input_paths = list(self.file_listbox.get(0, tk.END))
        if not input_paths: return

        out_dir = self.entry_out_dir.get().strip()
        custom_name = self.entry_out_name.get().strip()
        suffix = self.entry_suffix.get().strip()
        overwrite = self.overwrite_var.get()
        
        m_str = self.method_combo.get()
        if "Crepe" in m_str: detect_method = "crepe"
        elif "Harvest" in m_str: detect_method = "harvest"
        elif "Dio" in m_str: detect_method = "dio"
        else: detect_method = "pyin"
        
        model = self.model_var.get()
        threshold = self.thresh_val.get()
        pitch = self.pitch_val.get()
        eq_rules = self._get_rules()
        res_gain = self.res_scale.get()
        
        f0_min = self.f0_min_var.get()
        f0_max = self.f0_max_var.get()

        if not eq_rules and res_gain == 0 and pitch == 0:
            if not messagebox.askyesno("確認", "設定が初期値(変更なし)のままです。実行しますか？"):
                return

        self.btn_process.config(state=tk.DISABLED)
        self.progress['value'] = 0
        self.lbl_status.config(text="処理開始...")
        
        threading.Thread(
            target=processing_thread,
            args=(input_paths, out_dir, custom_name, suffix, overwrite, detect_method, model, 
                  eq_rules, res_gain, threshold, pitch, f0_min, f0_max, self.is_folder_mode, self.q),
            daemon=True
        ).start()

    def _check_queue(self):
        try:
            while True:
                msg = self.q.get_nowait()
                if isinstance(msg, tuple):
                    if msg[0] == "SHOW_INFO": messagebox.showinfo(msg[1], msg[2])
                    elif msg[0] == "SHOW_WARNING": messagebox.showwarning(msg[1], msg[2])
                    elif msg[0] == "SHOW_ERROR": messagebox.showerror(msg[1], msg[2])
                    elif msg[0] == "INIT_PROGRESS":
                        self.progress["maximum"] = msg[1]
                        self.progress["value"] = 0
                    elif msg[0] == "UPDATE_PROGRESS":
                        self.progress["value"] += msg[1]
                elif msg == "PROCESS_COMPLETE":
                    self.btn_process.config(state=tk.NORMAL)
                    self.lbl_status.config(text="待機中")
                else:
                    self.lbl_status.config(text=msg)
        except queue.Empty: pass
        finally: self.root.after(100, self._check_queue)

if __name__ == "__main__":
    root = tk.Tk()
    app = VoiceChangerEQApp(root)
    root.mainloop()