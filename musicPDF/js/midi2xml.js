/**
 * ScoreFlow - Multi-Part MIDI to MusicXML 4.0 Converter
 * Port, Channel, Tie-across-barline, and Japanese Encoding Support
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

  // 【文字化け復元】MIDIのトラック名（UTF-8 / Shift-JIS）がLatin-1として誤読された場合に日本語へ復元
  function decodeMidiText(rawStr) {
    if (!rawStr) return "";
    let hasHighByte = false;
    const bytes = [];
    for (let i = 0; i < rawStr.length; i++) {
      const code = rawStr.charCodeAt(i);
      bytes.push(code & 0xff);
      if (code >= 0x80) hasHighByte = true;
    }
    // 128以上のバイトが含まれていない純粋なASCIIならそのまま返す
    if (!hasHighByte) return rawStr;

    const uint8 = new Uint8Array(bytes);

    // 1. UTF-8としての復元を試みる
    try {
      return new TextDecoder("utf-8", { fatal: true }).decode(uint8);
    } catch (e1) {
      // 2. 日本のMIDIファイルに非常に多い Shift-JIS としての復元を試みる
      try {
        return new TextDecoder("shift-jis", { fatal: true }).decode(uint8);
      } catch (e2) {
        return rawStr;
      }
    }
  }

  // MIDIからトラック・チャンネル・ポート構成を柔軟に抽出 (Type 0 / Type 1 両対応)
  function extractPartProfiles(parsedMidi, splitMode = "channel") {
    const profiles = [];

    const allTrackEvents = [];
    parsedMidi.tracks.forEach((track, tIdx) => {
      if (!track.notes || track.notes.length === 0) return;

      let port = 1;
      if (track.port !== undefined) {
        port = track.port + 1;
      }

      const decodedTrackName = decodeMidiText(track.name ? track.name.trim() : "");
      const decodedInstName = decodeMidiText(track.instrument ? track.instrument.name : "");

      track.notes.forEach(note => {
        const ch = (note.channel !== undefined ? note.channel : (track.channel !== undefined ? track.channel : 0)) + 1;
        allTrackEvents.push({
          trackIndex: tIdx,
          trackName: decodedTrackName,
          instrumentName: decodedInstName,
          port: port,
          channel: ch,
          note: note
        });
      });
    });

    if (allTrackEvents.length === 0) return profiles;

    // 分割基準に応じたグルーピング
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

    const title = options.title || decodeMidiText(parsedMidi.header.name) || "Converted Score";
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

    let globalMaxTick = 0;
    parts.forEach(part => {
      part.notes.forEach(note => {
        const end = note.ticks + note.durationTicks;
        if (end > globalMaxTick) globalMaxTick = end;
      });
    });
    const totalMeasures = Math.max(1, Math.ceil(globalMaxTick / ticksPerMeasure));

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

    parts.forEach((part, pIdx) => {
      const partId = `P${pIdx + 1}`;
      xml += `  <part id="${partId}">\n`;

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

      // 小節境界をまたぐ音符を分割し、タイを付与
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
            tieStart: segEnd < curEnd,
            tieStop: curStart > note.startTick
          });

          curStart = segEnd;
        }
      });

      barlineSplitNotes.sort((a, b) => a.startTick - b.startTick || a.midi - b.midi);

      const clefSign = part.clef === 'F' ? 'F' : 'G';
      const clefLine = clefSign === 'F' ? '4' : '2';

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

  return { extractPartProfiles, convert, decodeMidiText };
})();
