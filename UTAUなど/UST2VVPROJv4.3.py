import json
import math
import uuid
import sys
import os

# ==========================================
# 定数・設定
# ==========================================
TPQN = 480
DEFAULT_BPM = 120.0
FRAME_RATE = 93.75 
FRAME_PERIOD = 1.0 / FRAME_RATE
VALUE_INDICATING_NO_DATA = -1.0

# ==========================================
# クラス定義
# ==========================================
class Mode1:
    def __init__(self):
        self.pb_type: str = "5"
        self.pitches: list = []
        self.pb_start: float = 0.0

class Mode2:
    def __init__(self):
        self.pbs: tuple = (0.0, 0.0)
        self.pbw: list = []
        self.pby: list = []
        self.pbm: list = []
        self.vbr: list = []

class Note:
    def __init__(self):
        self.lyric: str = ""
        self.length: int = 0
        self.note_num: int = 60
        self.tempo: float | None = None
        self.bpm: float = DEFAULT_BPM
        
        self.has_mode1: bool = False
        self.has_mode2: bool = False
        self.mode1: Mode1 = Mode1()
        self.mode2: Mode2 = Mode2()
        
        # タイミング(絶対座標)
        self.start_tick: int = 0
        self.end_tick: int = 0
        self.start_sec: float = 0.0
        self.end_sec: float = 0.0

# ==========================================
# USTパース
# ==========================================
def parse_ust(file_path: str) -> tuple:
    lines = []
    try:
        with open(file_path, 'r', encoding='cp932') as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        except Exception as e:
            print(f"Error: Failed to open file. {e}")
            sys.exit(1)

    dicted_ust = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # セクションヘッダー判定
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1]
            if section == "#TRACKEND":
                break
            dicted_ust.append({})
        elif '=' in line:
            parts = line.split('=', 1)
            # ★修正: リスト末尾へのアクセス [-1]
            if len(dicted_ust) > 0:
                dicted_ust[-1][parts[0].strip()] = parts[1].strip()

    global_bpm = DEFAULT_BPM
    notes = []
    
    for d in dicted_ust:
        if "Tempo" in d and "Length" not in d:
            try: global_bpm = float(d["Tempo"])
            except: pass
            continue
            
        if "Length" not in d or "Lyric" not in d:
            continue
            
        note = Note()
        note.lyric = d["Lyric"]
        try: note.length = int(d["Length"])
        except: note.length = 480
        
        try: note.note_num = int(d.get("NoteNum", "60"))
        except: note.note_num = 60
            
        if "Tempo" in d:
            try: note.tempo = float(d["Tempo"])
            except: pass

        # --- Mode1 解析 ---
        pb_str = ""
        if "PitchBend" in d:
            pb_str = d["PitchBend"]
        elif "Pitches" in d:
            pb_str = d["Pitches"]
            
        if "PBType" in d or pb_str:
            note.has_mode1 = True
            note.mode1.pb_type = d.get("PBType", "5")
            if pb_str:
                for j in pb_str.split(','):
                    try: note.mode1.pitches.append(int(j) if j.strip() else 0)
                    except ValueError: note.mode1.pitches.append(0)
            try: note.mode1.pb_start = float(d.get("PBStart", "0"))
            except: note.mode1.pb_start = 0.0

        # --- Mode2 解析 ---
        if "PBS" in d:
            note.has_mode2 = True
            pbs_str = d["PBS"]
            if ';' in pbs_str:
                parts = pbs_str.split(';')
                try: note.mode2.pbs = (float(parts[0]), float(parts[1]))
                except: note.mode2.pbs = (0.0, 0.0)
            else:
                try: note.mode2.pbs = (float(pbs_str), 0.0)
                except: note.mode2.pbs = (0.0, 0.0)
                
            # 空文字は0.0として扱う
            if "PBW" in d:
                for j in d["PBW"].split(','):
                    try: note.mode2.pbw.append(float(j) if j.strip() else 0.0)
                    except ValueError: note.mode2.pbw.append(0.0)
            if "PBY" in d:
                for j in d["PBY"].split(','):
                    try: note.mode2.pby.append(float(j) if j.strip() else 0.0)
                    except ValueError: note.mode2.pby.append(0.0)
            if "PBM" in d:
                for j in d["PBM"].split(','):
                    note.mode2.pbm.append(j.strip())
            if "VBR" in d:
                vbr_parts = d["VBR"].split(',')
                limit = max(0, len(vbr_parts) - 2) if len(vbr_parts) > 2 else len(vbr_parts)
                for i in range(limit):
                    val = vbr_parts[i].strip()
                    try: note.mode2.vbr.append(float(val) if val else 0.0)
                    except ValueError: note.mode2.vbr.append(0.0)
        
        notes.append(note)

    return notes, global_bpm

# ==========================================
# 時間計算
# ==========================================
def calculate_timing(notes: list, global_bpm: float):
    current_tick = 0
    current_sec = 0.0
    current_bpm = global_bpm

    for note in notes:
        if note.tempo is not None and note.tempo > 0:
            current_bpm = note.tempo
        
        note.bpm = current_bpm
        note.start_tick = current_tick
        note.end_tick = current_tick + note.length
        
        duration_sec = note.length * (60.0 / (current_bpm * TPQN))
        
        note.start_sec = current_sec
        note.end_sec = current_sec + duration_sec
        
        current_tick += note.length
        current_sec += duration_sec

# ==========================================
# ピッチ補間 (UTAU PBM仕様)
# ==========================================
def interpolate_pitch(t: float, x0: float, y0: float, x1: float, y1: float, mode: str) -> float:
    if x1 == x0:
        return y0
    
    ratio = max(0.0, min(1.0, (t - x0) / (x1 - x0)))
    
    if mode == "s":
        # Linear (直線)
        val = ratio
    elif mode == "j":
        # Ease-In (J型)
        val = ratio * ratio
    elif mode == "r":
        # Ease-Out (R型)
        val = 1.0 - (1.0 - ratio) * (1.0 - ratio)
    else:
        # Cosine (S字: デフォルト)
        val = (1.0 - math.cos(ratio * math.pi)) / 2.0
        
    return y0 + (y1 - y0) * val

def calculate_vibrato(t_rel_ms: float, note_dur_ms: float, vbr: list) -> float:
    # VBR: [Length, Period, Depth(cent), In, Out, Phase, Shift, High]
    if len(vbr) < 3 or vbr[0] <= 0:
        return 0.0
    
    v_len_pct = vbr[0]
    v_period = vbr[1]
    v_depth_cent = vbr[2] # 単位はcent
    v_fade_in_pct = vbr[3] if len(vbr) > 3 else 0.0
    v_fade_out_pct = vbr[4] if len(vbr) > 4 else 0.0
    v_phase_pct = vbr[5] if len(vbr) > 5 else 0.0
    v_shift_pct = vbr[6] if len(vbr) > 6 else 0.0
    
    vib_len_ms = note_dur_ms * (v_len_pct / 100.0)
    vib_start_ms = note_dur_ms - vib_len_ms
    
    if t_rel_ms < vib_start_ms:
        return 0.0
        
    t_vib = t_rel_ms - vib_start_ms
    amp = 1.0
    
    fi_time = vib_len_ms * (v_fade_in_pct / 100.0)
    fo_time = vib_len_ms * (v_fade_out_pct / 100.0)
    
    if fi_time > 0 and t_vib < fi_time:
        amp *= (t_vib / fi_time)
    
    time_left = vib_len_ms - t_vib
    if fo_time > 0 and time_left < fo_time:
        amp *= (max(0.0, time_left) / fo_time)
        
    if v_period > 0:
        phase = 2 * math.pi * (v_phase_pct / 100.0)
        shift_offset = v_depth_cent * (v_shift_pct / 100.0)
        val = math.sin(2 * math.pi * (t_vib / v_period) - phase)
        
        return (val * v_depth_cent + shift_offset) * amp

    return 0.0

# ==========================================
# ピッチデータ生成 (Hz配列)
# ==========================================
def generate_pitch_data(notes: list) -> list:
    if not notes:
        return []

    last_note = notes[-1]
    total_duration = last_note.end_sec + 2.0
    total_frames = int(math.ceil(total_duration * FRAME_RATE))
    
    # ★修正: リスト初期化
    pitch_data = [VALUE_INDICATING_NO_DATA] * total_frames
    
    for note in notes:
        if note.lyric == "R":
            continue
            
        note_dur_ms = (note.end_sec - note.start_sec) * 1000.0

        # --- Mode2 (PBS/PBW/PBY) ---
        if note.has_mode2:
            pbs_time, pbs_pitch_10c = note.mode2.pbs
            
            # 10cent単位 -> cent単位
            pbs_pitch_cent = pbs_pitch_10c * 10.0
            
            control_points = []
            t_accum = pbs_time
            control_points.append((t_accum, pbs_pitch_cent, ""))
            
            count = max(len(note.mode2.pbw), len(note.mode2.pby))
            for i in range(count):
                w = note.mode2.pbw[i] if i < len(note.mode2.pbw) else 0.0
                y_val_10c = note.mode2.pby[i] if i < len(note.mode2.pby) else 0.0
                m = note.mode2.pbm[i] if i < len(note.mode2.pbm) else ""
                
                y_cent = y_val_10c * 10.0
                t_accum += w
                control_points.append((t_accum, y_cent, m))
            
            start_time_sec = note.start_sec + (pbs_time / 1000.0)
            
            # ★修正: 最終制御点へのアクセス [-1]
            last_pt_time = control_points[-1][0] if control_points else 0.0
            end_time_sec = max(note.end_sec, note.start_sec + (last_pt_time / 1000.0))
            
            start_f = max(0, int(start_time_sec * FRAME_RATE))
            end_f = min(total_frames, int(end_time_sec * FRAME_RATE) + 1)
            
            for f in range(start_f, end_f):
                t_abs = f * FRAME_PERIOD
                t_rel_ms = (t_abs - note.start_sec) * 1000.0
                
                if t_rel_ms < pbs_time:
                    continue
                    
                pitch_offset_cent = 0.0
                # ★修正: インデックスアクセスを追加 [0][1], [-1][1]
                if len(control_points) == 1:
                    pitch_offset_cent = control_points[0][1]
                elif t_rel_ms >= control_points[-1][0]:
                    pitch_offset_cent = control_points[-1][1]
                else:
                    for i in range(len(control_points) - 1):
                        # ★修正: ループ内インデックスアクセス [i], [i+1]
                        x0, y0, _ = control_points[i]
                        x1, y1, mode = control_points[i+1]
                        if x0 <= t_rel_ms <= x1:
                            pitch_offset_cent = interpolate_pitch(t_rel_ms, x0, y0, x1, y1, mode)
                            break
                            
                pitch_offset_cent += calculate_vibrato(t_rel_ms, note_dur_ms, note.mode2.vbr)
                
                # Hz変換 (100cent = 1semitone)
                target_note_val = note.note_num + (pitch_offset_cent / 100.0)
                hz = 440.0 * (2.0 ** ((target_note_val - 69.0) / 12.0))
                
                if hz > 0:
                    pitch_data[f] = hz

        # --- Mode1 (PitchBend) ---
        elif note.has_mode1:
            pb_start_ms = note.mode1.pb_start
            pitches = note.mode1.pitches
            if not pitches:
                continue
                
            tick_ms = 60000.0 / (note.bpm * TPQN)
            step_ms = 5.0 * tick_ms
            
            start_time_sec = note.start_sec + (pb_start_ms / 1000.0)
            end_time_sec = start_time_sec + (len(pitches) * step_ms / 1000.0)
            
            start_f = max(0, int(start_time_sec * FRAME_RATE))
            end_f = min(total_frames, int(end_time_sec * FRAME_RATE) + 1)
            
            for f in range(start_f, end_f):
                t_abs = f * FRAME_PERIOD
                t_rel_ms = ((t_abs - note.start_sec) * 1000.0) - pb_start_ms
                
                if t_rel_ms < 0:
                    continue
                    
                idx = int(t_rel_ms / step_ms)
                
                if idx < 0:
                    pitch_cent = float(pitches[0])
                elif idx >= len(pitches) - 1:
                    pitch_cent = float(pitches[-1])
                else:
                    x0 = idx * step_ms
                    x1 = (idx + 1) * step_ms
                    # ★修正: インデックスアクセス [idx]
                    y0 = float(pitches[idx])
                    y1 = float(pitches[idx+1])
                    pitch_cent = interpolate_pitch(t_rel_ms, x0, y0, x1, y1, "s")
                
                target_note_val = note.note_num + (pitch_cent / 100.0)
                hz = 440.0 * (2.0 ** ((target_note_val - 69.0) / 12.0))
                
                if hz > 0:
                    pitch_data[f] = hz

    return pitch_data

# ==========================================
# VVPROJ 生成処理
# ==========================================
def generate_vvproj(ust_path: str, output_path: str):
    print(f"Loading UST: {ust_path}")
    notes, initial_bpm = parse_ust(ust_path)
    
    if not notes:
        print("Error: No notes found in UST.")
        return

    calculate_timing(notes, initial_bpm)
    
    vv_notes = []
    for n in notes:
        if n.lyric == "R":
            continue
        vv_notes.append({
            "id": str(uuid.uuid4()),
            "position": n.start_tick,
            "duration": n.length,
            "noteNumber": n.note_num,
            "lyric": n.lyric
        })

    print("Generating Pitch Curves...")
    pitch_edit_data = generate_pitch_data(notes)

    track_id = str(uuid.uuid4())
    vvproj = {
        "appVersion": "0.25.1",
        "talk": {"audioKeys": [], "audioItems": {}},
        "song": {
            "tpqn": TPQN,
            "tempos": [
                {
                    "position": 0,
                    "bpm": initial_bpm
                }
            ],
            "timeSignatures": [
                {
                    "measureNumber": 1,
                    "beats": 4,
                    "beatType": 4
                }
            ],
            "tracks": {
                track_id: {
                    "name": "Imported UST",
                    "singer": {
                        "engineId": "074fc39e-678b-4c13-8916-ffca8d505d1d",
                        "styleId": 3000
                    },
                    "keyRangeAdjustment": 0,
                    "volumeRangeAdjustment": 0,
                    "notes": vv_notes,
                    "pitchEditData": pitch_edit_data,
                    "volumeEditData": [],
                    "phonemeTimingEditData": {},
                    "solo": False,
                    "mute": False,
                    "gain": 1.0,
                    "pan": 0.0
                }
            },
            "trackOrder": [track_id]
        }
    }

    print(f"Writing VVPROJ: {output_path}")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(vvproj, f, indent=None, ensure_ascii=False)
    print("Done!")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python ust2vvproj_v9.py <input.ust>")
    else:
        # ★修正: sys.argvのインデックス
        input_ust = sys.argv[1]
        output_vv = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(input_ust)[0] + ".vvproj"
        generate_vvproj(input_ust, output_vv)
