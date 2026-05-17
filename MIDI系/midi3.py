import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import mido
import cv2
import numpy as np
import subprocess
import os
import threading
import random

# ==========================================
# 【重要】FluidSynthのパス設定
# ==========================================
# 環境変数にパスが通っていない場合はフルパスを記述してください
FLUIDSYNTH_CMD = "fluidsynth"

class MidiToVideoApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Universal MIDI Renderer (Horizontal & Vertical)")
        self.root.geometry("720x850")

        # --- 変数定義 ---
        self.midi_path = tk.StringVar()
        self.sf2_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.status_msg = tk.StringVar(value="準備完了")
        self.progress_val = tk.DoubleVar(value=0)
        
        self.force_default_sound = tk.BooleanVar(value=True)
        
        # 映像基本設定
        self.fps_var = tk.IntVar(value=30)
        self.width_var = tk.IntVar(value=1920)
        self.height_var = tk.IntVar(value=1080)

        # マージン設定 (px)
        self.margin_top = tk.IntVar(value=50)
        self.margin_bottom = tk.IntVar(value=50)
        self.margin_left = tk.IntVar(value=150) 
        self.margin_right = tk.IntVar(value=50)

        # 描画モードとオプション
        # 4つのモードを選択可能
        self.render_mode = tk.StringVar(value="Horizontal_RtoL") 
        self.time_window = tk.DoubleVar(value=4.0) # 画面内に表示する秒数

        self.show_piano = tk.BooleanVar(value=True)
        self.show_note_names = tk.BooleanVar(value=True)

        self.create_widgets()

    def create_widgets(self):
        # スクロールバー付きのキャンバスを作成（設定項目が増えたため）
        main_canvas = tk.Canvas(self.root)
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=main_canvas.yview)
        scrollable_frame = tk.Frame(main_canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all"))
        )

        main_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        main_canvas.configure(yscrollcommand=scrollbar.set)

        main_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # --- UI構築開始 ---
        pad_opts = {'padx': 10, 'pady': 5}
        
        # 1. ファイル選択
        file_frame = tk.LabelFrame(scrollable_frame, text="ファイル選択", **pad_opts)
        file_frame.pack(fill=tk.X, **pad_opts)
        self.make_file_input(file_frame, "MIDIファイル:", self.midi_path, [("MIDI", "*.mid"), ("All", "*.*")], 0)
        self.make_file_input(file_frame, "SoundFont:", self.sf2_path, [("SoundFont", "*.sf2"), ("All", "*.*")], 1)
        self.make_file_input(file_frame, "保存先 (mp4):", self.output_path, [("MP4", "*.mp4")], 2, save=True)

        # 2. レンダリングモード
        mode_frame = tk.LabelFrame(scrollable_frame, text="レンダリングモード (方向)", **pad_opts)
        mode_frame.pack(fill=tk.X, **pad_opts)
        
        modes = [
            ("横スクロール: 右から左 (標準)", "Horizontal_RtoL"),
            ("横スクロール: 左から右 (逆再生風)", "Horizontal_LtoR"),
            ("縦スクロール: 上から下 (落下/Synthesia)", "Vertical_Falling"),
            ("縦スクロール: 下から上 (上昇/音ゲー)", "Vertical_Rising"),
        ]
        
        for text, val in modes:
            tk.Radiobutton(mode_frame, text=text, variable=self.render_mode, value=val).pack(anchor="w", padx=10)

        # 3. 映像サイズ・速度
        size_frame = tk.LabelFrame(scrollable_frame, text="サイズ・速度設定", **pad_opts)
        size_frame.pack(fill=tk.X, **pad_opts)

        r1 = tk.Frame(size_frame)
        r1.pack(fill=tk.X)
        tk.Label(r1, text="幅:").pack(side=tk.LEFT)
        tk.Entry(r1, textvariable=self.width_var, width=6).pack(side=tk.LEFT, padx=5)
        tk.Label(r1, text="高さ:").pack(side=tk.LEFT)
        tk.Entry(r1, textvariable=self.height_var, width=6).pack(side=tk.LEFT, padx=5)
        tk.Label(r1, text="FPS:").pack(side=tk.LEFT)
        tk.Entry(r1, textvariable=self.fps_var, width=4).pack(side=tk.LEFT, padx=5)
        
        tk.Label(r1, text="表示秒数(流速):").pack(side=tk.LEFT, padx=(15,0))
        tk.Entry(r1, textvariable=self.time_window, width=4).pack(side=tk.LEFT, padx=5)
        tk.Label(r1, text="秒").pack(side=tk.LEFT)

        # 4. 余白設定
        margin_frame = tk.LabelFrame(scrollable_frame, text="余白設定 (px) - 鍵盤の置き場所確保用", **pad_opts)
        margin_frame.pack(fill=tk.X, **pad_opts)
        
        r2 = tk.Frame(margin_frame)
        r2.pack(fill=tk.X)
        tk.Label(r2, text="上:").pack(side=tk.LEFT)
        tk.Entry(r2, textvariable=self.margin_top, width=5).pack(side=tk.LEFT, padx=2)
        tk.Label(r2, text="下:").pack(side=tk.LEFT)
        tk.Entry(r2, textvariable=self.margin_bottom, width=5).pack(side=tk.LEFT, padx=2)
        tk.Label(r2, text="左:").pack(side=tk.LEFT)
        tk.Entry(r2, textvariable=self.margin_left, width=5).pack(side=tk.LEFT, padx=2)
        tk.Label(r2, text="右:").pack(side=tk.LEFT)
        tk.Entry(r2, textvariable=self.margin_right, width=5).pack(side=tk.LEFT, padx=2)
        
        tk.Label(margin_frame, text="※横モードなら左右、縦モードなら上下に鍵盤用の余白を確保してください。", fg="gray", font=("Meiryo", 8)).pack(anchor="w")

        # 5. オプション
        opt_frame = tk.LabelFrame(scrollable_frame, text="描画オプション", **pad_opts)
        opt_frame.pack(fill=tk.X, **pad_opts)

        tk.Checkbutton(opt_frame, text="ピアノ鍵盤を表示", variable=self.show_piano).pack(anchor="w")
        tk.Checkbutton(opt_frame, text="音名を表示 (C4など)", variable=self.show_note_names).pack(anchor="w", padx=20)
        tk.Checkbutton(opt_frame, text="楽器指定を無視 (全パートPiano化)", variable=self.force_default_sound).pack(anchor="w")

        # 6. 実行
        btn_run = tk.Button(scrollable_frame, text="変換開始", command=self.start_conversion_thread, bg="#E91E63", fg="white", font=("Meiryo", 12, "bold"), height=2)
        btn_run.pack(fill=tk.X, pady=20, padx=10)

        self.pb = ttk.Progressbar(scrollable_frame, variable=self.progress_val, maximum=100)
        self.pb.pack(fill=tk.X, padx=10)
        self.lbl_status = tk.Label(scrollable_frame, textvariable=self.status_msg, anchor="w", fg="blue")
        self.lbl_status.pack(fill=tk.X, padx=10)

    def make_file_input(self, parent, label_text, var, filetypes, row, save=False):
        tk.Label(parent, text=label_text).grid(row=row, column=0, sticky="e")
        tk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", padx=5)
        def select():
            if save: f = filedialog.asksaveasfilename(filetypes=filetypes, defaultextension=".mp4")
            else: f = filedialog.askopenfilename(filetypes=filetypes)
            if f: var.set(f)
        tk.Button(parent, text="参照", command=select).grid(row=row, column=2)
        parent.grid_columnconfigure(1, weight=1)

    def start_conversion_thread(self):
        if not self.midi_path.get() or not self.sf2_path.get() or not self.output_path.get():
            messagebox.showerror("エラー", "全てのファイルパスを指定してください。")
            return
        t = threading.Thread(target=self.run_conversion)
        t.start()

    def log(self, msg):
        self.status_msg.set(msg)
        print(msg)

    def create_sanitized_midi(self, input_path, output_path):
        mid = mido.MidiFile(input_path)
        new_mid = mido.MidiFile()
        new_mid.ticks_per_beat = mid.ticks_per_beat
        count = 0
        for track in mid.tracks:
            new_track = mido.MidiTrack()
            for msg in track:
                if msg.type == 'program_change': continue
                if msg.type == 'control_change' and msg.control in [0, 32]: continue
                if hasattr(msg, 'channel') and msg.channel == 9: msg.channel = 0
                if msg.type == 'note_on': count += 1
                new_track.append(msg)
            new_mid.tracks.append(new_track)
        new_mid.save(output_path)
        return count

    def run_conversion(self):
        try:
            original_midi = os.path.abspath(self.midi_path.get())
            sf2_file = os.path.abspath(self.sf2_path.get())
            output_file = os.path.abspath(self.output_path.get())
            
            temp_midi = "temp_u.mid"
            temp_wav = "temp_u.wav"
            temp_video = "temp_u.avi"

            target_midi = original_midi

            # 1. MIDI整形
            if self.force_default_sound.get():
                self.log("MIDI整形中...")
                cnt = self.create_sanitized_midi(original_midi, temp_midi)
                target_midi = temp_midi
                if cnt == 0: raise Exception("ノートが見つかりません")

            # 2. 音声生成
            self.log("音声生成中 (FluidSynth)...")
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            cmd_audio = [FLUIDSYNTH_CMD, '-ni', '-F', temp_wav, '-r', '44100', sf2_file, target_midi]
            subprocess.run(cmd_audio, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
            if not os.path.exists(temp_wav) or os.path.getsize(temp_wav) < 1000:
                raise Exception("音声生成エラー")

            # 3. 映像生成 (統合版関数)
            self.log("映像生成中...")
            self.generate_video_unified(target_midi, temp_video)

            # 4. 結合
            self.log("結合中 (FFmpeg)...")
            cmd_ffmpeg = [
                'ffmpeg', '-y', '-i', temp_video, '-i', temp_wav,
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'fast',
                '-c:a', 'aac', '-b:a', '192k', '-shortest', output_file
            ]
            subprocess.run(cmd_ffmpeg, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)

            self.log(f"完了: {output_file}")
            messagebox.showinfo("成功", "完了しました！")

        except Exception as e:
            self.log(f"エラー: {e}")
            messagebox.showerror("エラー", str(e))
        finally:
            for f in [temp_midi, temp_wav, temp_video]:
                if os.path.exists(f): os.remove(f)
            self.progress_val.set(0)

    # =========================================================================
    #  統合レンダリング関数 (横・縦 全対応)
    # =========================================================================
    def generate_video_unified(self, midi_path, video_out_path):
        # パラメータ取得
        W = self.width_var.get()
        H = self.height_var.get()
        fps = self.fps_var.get()
        mode = self.render_mode.get() # "Horizontal_RtoL", "Vertical_Falling", etc.
        
        m_top = self.margin_top.get()
        m_btm = self.margin_bottom.get()
        m_left = self.margin_left.get()
        m_right = self.margin_right.get()
        
        time_window = self.time_window.get()
        show_piano = self.show_piano.get()
        show_names = self.show_note_names.get()

        # モード判定
        is_vertical = "Vertical" in mode
        is_reverse = "LtoR" in mode or "Rising" in mode  # 逆方向(左から右、下から上)
        
        # MIDI読み込み
        mid = mido.MidiFile(midi_path)
        notes = []
        channel_colors = {}
        def get_color(ch):
            if ch not in channel_colors:
                channel_colors[ch] = (random.randint(80, 255), random.randint(80, 255), random.randint(80, 255))
            return channel_colors[ch]

        min_note, max_note = 21, 108
        abs_time = 0.0
        active_notes = {}
        
        for msg in mid:
            abs_time += msg.time
            if msg.type == 'note_on' and msg.velocity > 0:
                key = (msg.channel, msg.note)
                active_notes[key] = {'start': abs_time}
            elif (msg.type == 'note_off') or (msg.type == 'note_on' and msg.velocity == 0):
                key = (msg.channel, msg.note)
                if key in active_notes:
                    start_data = active_notes.pop(key)
                    if min_note <= msg.note <= max_note:
                        notes.append({
                            'note': msg.note,
                            'start': start_data['start'],
                            'end': abs_time,
                            'ch': msg.channel,
                            'color': get_color(msg.channel)
                        })
        
        duration = abs_time + 3.0
        total_frames = int(duration * fps)

        # 描画領域サイズ
        draw_w = W - m_left - m_right
        draw_h = H - m_top - m_btm
        
        if draw_w <= 0 or draw_h <= 0: raise Exception("マージンが大きすぎます")

        # 座標計算の定数
        total_keys = max_note - min_note + 1
        
        if is_vertical:
            # 縦モード: X軸=鍵盤, Y軸=時間
            key_step = draw_w / total_keys
            px_per_sec = draw_h / time_window
            # 判定ライン位置 (Fallingなら下、Risingなら上)
            hit_line_coord = (H - m_btm) if not is_reverse else m_top
        else:
            # 横モード: Y軸=鍵盤, X軸=時間
            key_step = draw_h / total_keys
            px_per_sec = draw_w / time_window
            # 判定ライン位置 (RtoLなら左、LtoRなら右)
            hit_line_coord = m_left if not is_reverse else (W - m_right)

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(video_out_path, fourcc, fps, (W, H))

        # ユーティリティ
        def is_black(n): return (n % 12) in [1, 3, 6, 8, 10]
        def get_name(n): return ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"][n%12] + str(n//12-1)

        for f in range(total_frames):
            now = f / fps
            img = np.full((H, W, 3), (20, 20, 20), dtype=np.uint8)

            # --- ノート描画 ---
            # 画面外はスキップ
            vis_min = now - time_window
            vis_max = now + time_window

            for n in notes:
                if n['end'] < vis_min or n['start'] > vis_max: continue
                
                # キー位置 (鍵盤軸)
                idx = n['note'] - min_note
                if not is_vertical:
                    # 横モード: 上が高音(idx小) or 下が高音？ 通常ピアノロールは上が高音
                    # max_noteが一番上(m_top)
                    k_pos = m_top + (max_note - n['note']) * key_step
                    k_thick = key_step + 1
                else:
                    # 縦モード: 左が低音
                    k_pos = m_left + idx * key_step
                    k_thick = key_step + 1

                # 時間位置 (スクロール軸)
                dt_start = n['start'] - now
                dt_end = n['end'] - now
                
                # 座標変換
                if is_vertical:
                    # 縦モード (X=k_pos, Y=variable)
                    x1, x2 = int(k_pos), int(k_pos + k_thick)
                    
                    if not is_reverse: # Falling (上から下へ) Noteは上にある(Y小)
                        y1 = int(hit_line_coord - dt_end * px_per_sec)
                        y2 = int(hit_line_coord - dt_start * px_per_sec)
                    else: # Rising (下から上へ) Noteは下にある(Y大)
                        y1 = int(hit_line_coord + dt_start * px_per_sec)
                        y2 = int(hit_line_coord + dt_end * px_per_sec)
                    
                    # 描画
                    color = (255,255,255) if n['start'] <= now < n['end'] else n['color']
                    # クリップ
                    if y2 < 0 or y1 > H: continue
                    cv2.rectangle(img, (x1, y1), (x2, y2), color, -1)
                    
                else:
                    # 横モード (Y=k_pos, X=variable)
                    y1, y2 = int(k_pos), int(k_pos + k_thick)
                    
                    if not is_reverse: # RtoL (右から左へ) Noteは右にある(X大)
                        x1 = int(hit_line_coord + dt_start * px_per_sec)
                        x2 = int(hit_line_coord + dt_end * px_per_sec)
                    else: # LtoR (左から右へ) Noteは左にある(X小)
                        x1 = int(hit_line_coord - dt_end * px_per_sec)
                        x2 = int(hit_line_coord - dt_start * px_per_sec)

                    color = (255,255,255) if n['start'] <= now < n['end'] else n['color']
                    if x2 < 0 or x1 > W: continue
                    cv2.rectangle(img, (x1, y1), (x2, y2), color, -1)

            # --- マージン塗りつぶし (はみ出し削除) ---
            # 上下
            cv2.rectangle(img, (0,0), (W, m_top), (10,10,10), -1)
            cv2.rectangle(img, (0,H-m_btm), (W,H), (10,10,10), -1)
            # 左右
            cv2.rectangle(img, (0,0), (m_left,H), (10,10,10), -1)
            cv2.rectangle(img, (W-m_right,0), (W,H), (10,10,10), -1)

            # --- 判定ライン & 鍵盤描画 ---
            if is_vertical:
                cv2.line(img, (0, int(hit_line_coord)), (W, int(hit_line_coord)), (200,200,200), 1)
                
                if show_piano:
                    # 鍵盤エリア計算
                    # FallingならBottomマージン内、RisingならTopマージン内
                    kb_y = hit_line_coord if not is_reverse else (hit_line_coord - m_top) # 簡易配置
                    kb_h = m_btm if not is_reverse else m_top
                    
                    # 描画位置微調整
                    draw_kb_y = int(hit_line_coord) if not is_reverse else int(hit_line_coord - kb_h)

                    for i in range(total_keys):
                        note_num = min_note + i
                        kx = int(m_left + i * key_step)
                        kw = int(key_step) + 1
                        
                        ib = is_black(note_num)
                        c = (40,40,40) if ib else (220,220,220)
                        
                        # 鍵盤矩形
                        cv2.rectangle(img, (kx, draw_kb_y), (kx+kw, draw_kb_y+kb_h), c, -1)
                        cv2.rectangle(img, (kx, draw_kb_y), (kx+kw, draw_kb_y+kb_h), (100,100,100), 1)

                        if show_names and not ib and (note_num%12==0):
                            cv2.putText(img, get_name(note_num), (kx, draw_kb_y+kb_h-10), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0,0,0), 1)

            else:
                # 横モード
                cv2.line(img, (int(hit_line_coord), 0), (int(hit_line_coord), H), (200,200,200), 1)
                
                if show_piano:
                    # RtoLならLeftマージン内、LtoRならRightマージン内
                    kb_x = 0 if not is_reverse else int(hit_line_coord)
                    kb_w = m_left if not is_reverse else m_right
                    
                    for i in range(total_keys):
                        note_num = max_note - i # 上が高音
                        ky = int(m_top + i * key_step)
                        kh = int(key_step) + 1
                        
                        ib = is_black(note_num)
                        c = (40,40,40) if ib else (220,220,220)
                        
                        cv2.rectangle(img, (kb_x, ky), (kb_x+kb_w, ky+kh), c, -1)
                        cv2.rectangle(img, (kb_x, ky), (kb_x+kb_w, ky+kh), (100,100,100), 1)
                        
                        if show_names and not ib and (note_num%12==0):
                            cv2.putText(img, get_name(note_num), (kb_x+5, ky+int(kh*0.7)), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0,0,0), 1)

            out.write(img)
            
            # プログレスバー
            prog = (f / total_frames) * 100
            if prog > self.progress_val.get() + 1:
                self.progress_val.set(prog)
                self.root.update_idletasks()

        out.release()

if __name__ == "__main__":
    root = tk.Tk()
    app = MidiToVideoApp(root)
    root.mainloop()
