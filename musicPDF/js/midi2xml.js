/**
 * ScoreFlow - Multi-Part MIDI to MusicXML 4.0 Converter
 * Port, Channel, Tie-across-barline support
 */
const Midi2Xml = (() => {
  const PITCH_CLASSES = ['C', 'C', 'D', 'D', 'E', 'F', 'F', 'G', 'G', 'A', 'A', 'B'];
  const ALTER_MAP = [0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1, 0];

  function durationToNoteType(durTicks, ppq) {
    const quarters = durTicks / ppq;
    if (quarters >= 3.5) return 'whole';
    if (quarters >= 1.75) return 'half';
    if (quarters >= 0.85) return 'quarter';
    if (quarters >= 0.4) return 'eighth';
    if (quarters >= 0.2) return '16th';
    return '32nd';
  }

  // MIDIからトラック・チャンネル・ポート構成を柔軟に抽出 (Type 0 / Type 1 両対応)
  function extractPartProfiles(parsedMidi, splitMode = "channel") {
    const profiles = [];

    // 1. 各トラックからノートをチャンネル・ポート情報付きで収集
    const allTrackEvents = [];
    parsedMidi.tracks.forEach((track, tIdx) => {
      if (!track.notes || track.notes.length === 0) return;

      // トラック内ポートの検出 (Meta 0x21 または default 1)
      let port = 1;
      if (track.port !== undefined) {
        port = track.port + 1;
      }

      track.notes.forEach(note => {
        // note.channel (0-15) または track.channel (0-15)
        const ch = (note.channel !== undefined ? note.channel : (track.channel !== undefined ? track.channel : 0)) + 1;
        allTrackEvents.push({
          trackIndex: tIdx,
          trackName: track.name ? track.name.trim() : "",
          instrumentName: track.instrument ? track.instrument.name : "",
          port: port,
          channel: ch,
          note: note
        });
      });
    });

    if (allTrackEvents.length === 0) return profiles;

    // 2. 分割基準に応じたグルーピング
    const groups = new Map();
    allTrackEvents.forEach(item => {
      let key = "";
      let groupName = "";

      if (splitMode === "track") {
        key = `T_${item.trackIndex}`;
        groupName = item.trackName || item.instrumentName || `Track ${item.trackIndex + 1}`;
      } else if (splitMode === "track_channel") {
        key = `T_${item.trackIndex}_C_${item.channel}`;
        groupName = item.trackName ? `${item.trackName} (ch ${item.channel})` : `Track ${item.trackIndex + 1} (ch ${item.channel})`;
      } else {
        // デフォルト: チャンネル別 (Type 0 MIDIでも確実にパート分離される)
        key = `P_${item.port}_C_${item.channel}`;
        groupName = item.instrumentName || item.trackName || `Channel ${item.channel}`;
      }

      if (!groups.has(key)) {
        groups.set(key, {
          key: key,
          port: item.port,
          channel: item.channel,
          name: groupName,
          notes: []
        });
      }
      groups.get(key).notes.push(item.note);
    });

    // 3. パートプロファイルを構築
    let pIdx = 1;
    groups.forEach((group) => {
      const avgPitch = group.notes.reduce((sum, n) => sum + n.midi, 0) / group.notes.length;
      const defaultClef = avgPitch < 55 ? 'F' : 'G';

      profiles.push({
        partId: `P${pIdx++}`,
        port: group.port,
        channel: group.channel,
        name: group.name,
        clef: defaultClef,
        enabled: true,
        noteCount: group.notes.length,
        notes: group.notes
      });
    });

    return profiles;
  }

  // マルチパート MusicXML 4.0 を生成
  function convert(parsedMidi, options = {}) {
    const ppq = parsedMidi.header.ppq || 480;
    const quantizeDivision = parseInt(options.quantize || 16, 10);
    const gridTicks = Math.round((ppq * 4) / quantizeDivision);

    const title = options.title || parsedMidi.header.name || "Converted Score";
    const composer = options.composer || "";

    let beats = 4;
    let beatType = 4;
    if (parsedMidi.header.timeSignatures && parsedMidi.header.timeSignatures.length > 0) {
      beats = parsedMidi.header.timeSignatures[0].timeSignature[0];
      beatType = parsedMidi.header.timeSignatures[0].timeSignature[1];
    }
    const ticksPerMeasure = Math.round(beats * (ppq * 4 / beatType));

    const parts = (options.parts && options.parts.length > 0)
      ? options.parts.filter(p => p.enabled && p.notes && p.notes.length > 0)
      : extractPartProfiles(parsedMidi, options.splitMode || "channel");

    if (parts.length === 0) {
      throw new Error("有効な音符を持つパートが存在しません。");
    }

    // 全体の最大小節数を計算
    let globalMaxTick = 0;
    parts.forEach(part => {
      part.notes.forEach(note => {
        const end = note.ticks + note.durationTicks;
        if (end > globalMaxTick) globalMaxTick = end;
      });
    });
    const totalMeasures = Math.max(1, Math.ceil(globalMaxTick / ticksPerMeasure));

    // XMLヘッダー・パートリスト構築 (MusicXML 4.0 port / channel 仕様)
    let xml = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="4.0">
  <work>
    <work-title>${escapeXml(title)}</work-title>
  </work>
  ${composer ? `<identification><creator type="composer">${escapeXml(composer)}</creator></identification>` : ''}
  <part-list>
`;

    parts.forEach((part, pIdx) => {
      const partId = `P${pIdx + 1}`;
      xml += `    <score-part id="${partId}">
      <part-name>${escapeXml(part.name)}</part-name>
      <score-instrument id="${partId}-I1">
        <instrument-name>${escapeXml(part.name)}</instrument-name>
      </score-instrument>
      <midi-device id="${partId}-I1" port="${part.port || 1}">Port ${part.port || 1}</midi-device>
      <midi-instrument id="${partId}-I1">
        <midi-channel>${part.channel || 1}</midi-channel>
      </midi-instrument>
    </score-part>\n`;
    });
    xml += `  </part-list>\n`;

    // 各パートの構築
    parts.forEach((part, pIdx) => {
      const partId = `P${pIdx + 1}`;
      xml += `  <part id="${partId}">\n`;

      // 1. クオンタイズ処理
      const quantNotes = [];
      part.notes.forEach(note => {
        const start = Math.round(note.ticks / gridTicks) * gridTicks;
        const dur = Math.max(gridTicks, Math.round(note.durationTicks / gridTicks) * gridTicks);
        quantNotes.push({
          midi: note.midi,
          startTick: start,
          endTick: start + dur,
          durationTicks: dur
        });
      });

      // 2. 【最重要】小節境界（Barline）をまたぐ音符を分割し、タイ（Tie）を付与
      const barlineSplitNotes = [];
      quantNotes.forEach(note => {
        let curStart = note.startTick;
        const curEnd = note.endTick;

        while (curStart < curEnd) {
          const mIndex = Math.floor(curStart / ticksPerMeasure);
          const mLimit = (mIndex + 1) * ticksPerMeasure;
          const segEnd = Math.min(curEnd, mLimit);

          barlineSplitNotes.push({
            midi: note.midi,
            startTick: curStart,
            endTick: segEnd,
            durationTicks: segEnd - curStart,
            tieStart: segEnd < curEnd, // 次小節へタイで接続
            tieStop: curStart > note.startTick // 前小節からタイで接続
          });

          curStart = segEnd;
        }
      });

      barlineSplitNotes.sort((a, b) => a.startTick - b.startTick || a.midi - b.midi);

      const clefSign = part.clef === 'F' ? 'F' : 'G';
      const clefLine = clefSign === 'F' ? '4' : '2';

      // 3. 小節単位の出力
      for (let m = 0; m < totalMeasures; m++) {
        const mStart = m * ticksPerMeasure;
        const mEnd = mStart + ticksPerMeasure;
        xml += `    <measure number="${m + 1}">\n`;

        if (m === 0) {
          xml += `      <attributes>
        <divisions>${ppq}</divisions>
        <key><fifths>0</fifths></key>
        <time><beats>${beats}</beats><beat-type>${beatType}</beat-type></time>
        <clef><sign>${clefSign}</sign><line>${clefLine}</line></clef>
      </attributes>\n`;
        }

        const mNotes = barlineSplitNotes.filter(n => n.startTick >= mStart && n.startTick < mEnd);

        if (mNotes.length === 0) {
          xml += `      <note>
        <rest/>
        <duration>${ticksPerMeasure}</duration>
        <voice>1</voice>
        <type>whole</type>
      </note>\n`;
        } else {
          let cursor = mStart;
          for (let i = 0; i < mNotes.length; i++) {
            const curNote = mNotes[i];
            const isChord = i > 0 && curNote.startTick === mNotes[i - 1].startTick;

            // 休符の挿入
            if (!isChord && curNote.startTick > cursor) {
              const restDur = curNote.startTick - cursor;
              xml += `      <note>
        <rest/>
        <duration>${restDur}</duration>
        <voice>1</voice>
        <type>${durationToNoteType(restDur, ppq)}</type>
      </note>\n`;
              cursor = curNote.startTick;
            }

            // 同一ボイス内の衝突防止クランプ
            let nextNonChordTick = mEnd;
            for (let j = i + 1; j < mNotes.length; j++) {
              if (mNotes[j].startTick > curNote.startTick) {
                nextNonChordTick = mNotes[j].startTick;
                break;
              }
            }

            const effEnd = Math.min(nextNonChordTick, Math.min(mEnd, curNote.endTick));
            const dur = Math.max(gridTicks, effEnd - curNote.startTick);

            const step = PITCH_CLASSES[curNote.midi % 12];
            const alter = ALTER_MAP[curNote.midi % 12];
            const octave = Math.floor(curNote.midi / 12) - 1;

            // タイタグの組み立て
            let tieXml = "";
            let tiedXml = "";
            if (curNote.tieStop) {
              tieXml += `<tie type="stop"/>`;
              tiedXml += `<tied type="stop"/>`;
            }
            if (curNote.tieStart) {
              tieXml += `<tie type="start"/>`;
              tiedXml += `<tied type="start"/>`;
            }
            const notationsXml = tiedXml ? `<notations>${tiedXml}</notations>` : '';

            xml += `      <note>
        ${isChord ? '<chord/>' : ''}
        <pitch>
          <step>${step}</step>
          ${alter !== 0 ? `<alter>${alter}</alter>` : ''}
          <octave>${octave}</octave>
        </pitch>
        <duration>${dur}</duration>
        ${tieXml}
        <voice>1</voice>
        <type>${durationToNoteType(dur, ppq)}</type>
        ${notationsXml}
      </note>\n`;

            if (!isChord) {
              cursor = Math.max(cursor, curNote.startTick + dur);
            }
          }

          if (cursor < mEnd) {
            const restDur = mEnd - cursor;
            xml += `      <note>
        <rest/>
        <duration>${restDur}</duration>
        <voice>1</voice>
        <type>${durationToNoteType(restDur, ppq)}</type>
      </note>\n`;
          }
        }

        xml += `    </measure>\n`;
      }
      xml += `  </part>\n`;
    });

    xml += `</score-partwise>`;
    return xml;
  }

  function escapeXml(unsafe) {
    if (!unsafe) return "";
    return unsafe.replace(/[<>&'"]/g, c => {
      switch (c) {
        case '<': return '&lt;';
        case '>': return '&gt;';
        case '&': return '&amp;';
        case '\'': return '&apos;';
        case '"': return '&quot;';
      }
    });
  }

  return { extractPartProfiles, convert };
})();
