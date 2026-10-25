document.addEventListener("DOMContentLoaded", () => {
  const container = document.getElementById("osmd-container");
  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("file-input");
  const statusBar = document.getElementById("status-bar");
  const editorPanel = document.getElementById("editor-panel");

  const metaTitle = document.getElementById("meta-title");
  const metaComposer = document.getElementById("meta-composer");
  const partTableBody = document.getElementById("part-table-body");
  const btnApplyMeta = document.getElementById("btn-apply-meta");
  const splitModeUnit = document.getElementById("split-mode-unit");
  const splitModeSelect = document.getElementById("split-mode-select");

  const viewModeSelect = document.getElementById("view-mode-select");
  const formatSelect = document.getElementById("format-select");
  const measuresSelect = document.getElementById("measures-select");
  const scaleSlider = document.getElementById("scale-slider");
  const scaleLabel = document.getElementById("scale-label");
  const quantizeSelect = document.getElementById("quantize-select");

  const btnExportXml = document.getElementById("btn-export-xml");
  const btnDownloadPdf = document.getElementById("btn-download-pdf");
  const btnPrintSheet = document.getElementById("btn-print-sheet");

  let parsedMidiData = null;
  let currentParts = [];
  let currentXmlContent = null;
  let currentFileName = "score";
  let isMidiMode = false;

  const PAPER_FORMATS = {
    "A4_P":     { osmdOption: "A4_P",     widthMm: 210,   heightMm: 297,   canvasWidthPx: 1050 },
    "A4_L":     { osmdOption: "A4_L",     widthMm: 297,   heightMm: 210,   canvasWidthPx: 1480 },
    "Letter_P": { osmdOption: "Letter_P", widthMm: 215.9, heightMm: 279.4, canvasWidthPx: 1080 },
    "Letter_L": { osmdOption: "Letter_L", widthMm: 279.4, heightMm: 215.9, canvasWidthPx: 1400 },
    "A3_P":     { osmdOption: "A3_P",     widthMm: 297,   heightMm: 420,   canvasWidthPx: 1480 },
    "A3_L":     { osmdOption: "A3_L",     widthMm: 420,   heightMm: 297,   canvasWidthPx: 2100 }
  };

  container.style.width = "1050px";

  const osmd = new opensheetmusicdisplay.OpenSheetMusicDisplay(container, {
    autoResize: false,
    backend: "svg",
    drawingParameters: "default",
    drawTitle: true,
    pageFormat: "A4_P",
    pageBackgroundColor: "#ffffff"
  });

  function showStatus(message, isError = false) {
    statusBar.style.display = "block";
    statusBar.textContent = message;
    statusBar.style.color = isError ? "#b91c1c" : "#334155";
    statusBar.style.borderLeftColor = isError ? "#ef4444" : "var(--accent-blue)";
  }

  // ファイル読み込み処理
  async function handleFile(file) {
    if (!file) return;
    currentFileName = file.name.replace(/\.[^/.]+$/, "");
    showStatus(`解析中: ${file.name}`);

    try {
      const ext = file.name.split('.').pop().toLowerCase();
      isMidiMode = (ext === 'mid' || ext === 'midi');

      if (isMidiMode) {
        splitModeUnit.style.display = "flex";
        const buffer = await file.arrayBuffer();
        parsedMidiData = new Midi(buffer);

        currentParts = Midi2Xml.extractPartProfiles(parsedMidiData, splitModeSelect.value);
        metaTitle.value = parsedMidiData.header.name || currentFileName;
        metaComposer.value = "";

        buildPartTable();
        await rebuildMidiXmlAndRender();
      } else {
        // MusicXML
        splitModeUnit.style.display = "none";
        parsedMidiData = null;

        if (ext === 'mxl') {
          const buffer = await file.arrayBuffer();
          await osmd.load(buffer);
          // mxlの場合は内部のMusicXMLをテキストとして抽出不可のため再ロード用フラグをクリア
          currentXmlContent = null;
        } else {
          let text = await file.text();
          text = text.replace(/<!DOCTYPE[\s\S]*?>/i, '');
          text = text.replace(/&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)/g, '&amp;');
          currentXmlContent = text;
          await osmd.load(text);
        }

        extractMusicXmlData();
        applyLayoutAndRender();
      }

      editorPanel.style.display = "block";
      updateViewModeOptions();

      showStatus(`描画完了: ${file.name}`);
      btnExportXml.disabled = !currentXmlContent;
      btnDownloadPdf.disabled = false;
      btnPrintSheet.disabled = false;
      viewModeSelect.disabled = false;

    } catch (err) {
      console.error(err);
      showStatus(`読み込みエラー: ${err.message}`, true);
    }
  }

  // MIDI用のパート設定テーブル生成
  function buildPartTable() {
    partTableBody.innerHTML = "";
    currentParts.forEach((part, idx) => {
      const tr = document.createElement("tr");

      tr.innerHTML = `
        <td style="text-align: center;">
          <input type="checkbox" class="part-enable" data-idx="${idx}" ${part.enabled ? 'checked' : ''} />
        </td>
        <td>
          <input type="number" class="part-port-input" data-idx="${idx}" min="1" max="16" value="${part.port || 1}" />
        </td>
        <td>
          <input type="number" class="part-ch-input" data-idx="${idx}" min="1" max="16" value="${part.channel || 1}" />
        </td>
        <td>
          <input type="text" class="part-name-input" data-idx="${idx}" value="${escapeAttr(part.name)}" />
        </td>
        <td>
          <select class="part-clef-select" data-idx="${idx}">
            <option value="G" ${part.clef === 'G' ? 'selected' : ''}>ト音記号 (G)</option>
            <option value="F" ${part.clef === 'F' ? 'selected' : ''}>ヘ音記号 (F)</option>
          </select>
        </td>
        <td style="text-align: right; color: var(--text-muted);">${part.noteCount}</td>
      `;
      partTableBody.appendChild(tr);
    });

    partTableBody.querySelectorAll(".part-enable").forEach(cb => {
      cb.addEventListener("change", (e) => {
        currentParts[parseInt(e.target.dataset.idx, 10)].enabled = e.target.checked;
      });
    });

    partTableBody.querySelectorAll(".part-port-input").forEach(inp => {
      inp.addEventListener("change", (e) => {
        currentParts[parseInt(e.target.dataset.idx, 10)].port = parseInt(e.target.value, 10) || 1;
      });
    });

    partTableBody.querySelectorAll(".part-ch-input").forEach(inp => {
      inp.addEventListener("change", (e) => {
        currentParts[parseInt(e.target.dataset.idx, 10)].channel = parseInt(e.target.value, 10) || 1;
      });
    });

    partTableBody.querySelectorAll(".part-name-input").forEach(inp => {
      inp.addEventListener("change", (e) => {
        currentParts[parseInt(e.target.dataset.idx, 10)].name = e.target.value.trim() || `Part ${parseInt(e.target.dataset.idx, 10) + 1}`;
      });
    });

    partTableBody.querySelectorAll(".part-clef-select").forEach(sel => {
      sel.addEventListener("change", (e) => {
        currentParts[parseInt(e.target.dataset.idx, 10)].clef = e.target.value;
      });
    });
  }

  // MusicXMLからメタデータとパート抽出
  function extractMusicXmlData() {
    metaTitle.value = osmd.sheet.TitleString || currentFileName;
    metaComposer.value = osmd.sheet.ComposerString || "";

    partTableBody.innerHTML = "";
    currentParts = [];

    // DOMからポートとチャンネルの取得を試みる
    let doc = null;
    if (currentXmlContent) {
      try {
        doc = new DOMParser().parseFromString(currentXmlContent, "application/xml");
      } catch (e) { /* ignore */ }
    }

    osmd.sheet.Instruments.forEach((inst, idx) => {
      let port = 1;
      let ch = 1;

      if (doc) {
        const scoreParts = doc.querySelectorAll("part-list score-part");
        if (scoreParts[idx]) {
          const mDev = scoreParts[idx].querySelector("midi-device");
          if (mDev && mDev.getAttribute("port")) {
            port = parseInt(mDev.getAttribute("port"), 10) || 1;
          }
          const mInst = scoreParts[idx].querySelector("midi-instrument midi-channel");
          if (mInst) {
            ch = parseInt(mInst.textContent, 10) || 1;
          }
        }
      }

      const pName = inst.NameLabel ? inst.NameLabel.text : `Part ${idx + 1}`;
      currentParts.push({
        osmdIndex: idx,
        name: pName,
        port: port,
        channel: ch,
        enabled: inst.Visible
      });

      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td style="text-align: center;">
          <input type="checkbox" class="part-enable" data-idx="${idx}" ${inst.Visible ? 'checked' : ''} />
        </td>
        <td>
          <input type="number" class="part-port-input" data-idx="${idx}" min="1" max="16" value="${port}" />
        </td>
        <td>
          <input type="number" class="part-ch-input" data-idx="${idx}" min="1" max="16" value="${ch}" />
        </td>
        <td>
          <input type="text" class="part-name-input" data-idx="${idx}" value="${escapeAttr(pName)}" />
        </td>
        <td style="color: var(--text-muted);">XML定義準拠</td>
        <td style="text-align: right; color: var(--text-muted);">-</td>
      `;
      partTableBody.appendChild(tr);
    });

    partTableBody.querySelectorAll(".part-enable").forEach(cb => {
      cb.addEventListener("change", (e) => {
        const idx = parseInt(e.target.dataset.idx, 10);
        osmd.sheet.Instruments[idx].Visible = e.target.checked;
        applyLayoutAndRender();
      });
    });

    partTableBody.querySelectorAll(".part-port-input").forEach(inp => {
      inp.addEventListener("change", (e) => {
        const idx = parseInt(e.target.dataset.idx, 10);
        currentParts[idx].port = parseInt(e.target.value, 10) || 1;
      });
    });

    partTableBody.querySelectorAll(".part-ch-input").forEach(inp => {
      inp.addEventListener("change", (e) => {
        const idx = parseInt(e.target.dataset.idx, 10);
        currentParts[idx].channel = parseInt(e.target.value, 10) || 1;
      });
    });

    partTableBody.querySelectorAll(".part-name-input").forEach(inp => {
      inp.addEventListener("change", (e) => {
        const idx = parseInt(e.target.dataset.idx, 10);
        currentParts[idx].name = e.target.value.trim() || `Part ${idx + 1}`;
      });
    });
  }

  // 表示スコア（Full Score / 単独パート）の切り替えプルダウン
  function updateViewModeOptions() {
    viewModeSelect.innerHTML = `<option value="all">Full Score (総譜)</option>`;
    if (isMidiMode) {
      currentParts.forEach((p, idx) => {
        if (p.enabled) {
          viewModeSelect.innerHTML += `<option value="${idx}">Part: ${escapeAttr(p.name)} [P${p.port || 1}:ch${p.channel || 1}]</option>`;
        }
      });
    } else if (osmd.sheet) {
      osmd.sheet.Instruments.forEach((inst, idx) => {
        const name = inst.NameLabel ? inst.NameLabel.text : `Part ${idx + 1}`;
        viewModeSelect.innerHTML += `<option value="${idx}">Part: ${escapeAttr(name)}</option>`;
      });
    }
  }

  // MIDI XML再構築
  async function rebuildMidiXmlAndRender() {
    currentXmlContent = Midi2Xml.convert(parsedMidiData, {
      title: metaTitle.value.trim() || currentFileName,
      composer: metaComposer.value.trim(),
      quantize: quantizeSelect.value,
      parts: currentParts,
      splitMode: splitModeSelect.value
    });

    await osmd.load(currentXmlContent);
    filterVisiblePart();
    applyLayoutAndRender();
    updateViewModeOptions();
    btnExportXml.disabled = false;
  }

  // MusicXML DOM書き換えによる確実な同期
  async function syncMusicXmlAndReload() {
    if (!currentXmlContent) return;

    try {
      const parser = new DOMParser();
      const doc = parser.parseFromString(currentXmlContent, "application/xml");

      // タイトル
      let workTitle = doc.querySelector("work work-title");
      if (!workTitle) {
        let work = doc.querySelector("work");
        if (!work) {
          work = doc.createElement("work");
          doc.documentElement.insertBefore(work, doc.documentElement.firstChild);
        }
        workTitle = doc.createElement("work-title");
        work.appendChild(workTitle);
      }
      workTitle.textContent = metaTitle.value.trim() || currentFileName;

      // 作曲者
      if (metaComposer.value.trim()) {
        let comp = doc.querySelector("identification creator[type='composer']");
        if (!comp) {
          let ident = doc.querySelector("identification");
          if (!ident) {
            ident = doc.createElement("identification");
            const partList = doc.querySelector("part-list");
            doc.documentElement.insertBefore(ident, partList);
          }
          comp = doc.createElement("creator");
          comp.setAttribute("type", "composer");
          ident.appendChild(comp);
        }
        comp.textContent = metaComposer.value.trim();
      }

      // パート名、ポート、チャンネル
      const scoreParts = doc.querySelectorAll("part-list score-part");
      scoreParts.forEach((sp, idx) => {
        if (currentParts[idx]) {
          let pName = sp.querySelector("part-name");
          if (!pName) {
            pName = doc.createElement("part-name");
            sp.appendChild(pName);
          }
          pName.textContent = currentParts[idx].name;

          let mDev = sp.querySelector("midi-device");
          if (!mDev) {
            mDev = doc.createElement("midi-device");
            sp.appendChild(mDev);
          }
          mDev.setAttribute("port", currentParts[idx].port || 1);

          let mInst = sp.querySelector("midi-instrument midi-channel");
          if (!mInst) {
            let parentInst = sp.querySelector("midi-instrument");
            if (!parentInst) {
              parentInst = doc.createElement("midi-instrument");
              parentInst.setAttribute("id", `${sp.getAttribute("id")}-I1`);
              sp.appendChild(parentInst);
            }
            mInst = doc.createElement("midi-channel");
            parentInst.appendChild(mInst);
          }
          mInst.textContent = currentParts[idx].channel || 1;
        }
      });

      currentXmlContent = new XMLSerializer().serializeToString(doc);
      await osmd.load(currentXmlContent);
      filterVisiblePart();
      applyLayoutAndRender();
      updateViewModeOptions();
    } catch (err) {
      console.error("XML同期失敗:", err);
    }
  }

  // 表示パートのフィルタリング
  function filterVisiblePart() {
    if (!osmd.sheet) return;
    const mode = viewModeSelect.value;

    if (mode === "all") {
      osmd.sheet.Instruments.forEach((inst, idx) => {
        const isEnabled = currentParts[idx] ? currentParts[idx].enabled : true;
        inst.Visible = isEnabled;
      });
    } else {
      const selectedIdx = parseInt(mode, 10);
      osmd.sheet.Instruments.forEach((inst, idx) => {
        inst.Visible = (idx === selectedIdx);
      });
    }
  }

  // レイアウト反映
  function applyLayoutAndRender() {
    if (!osmd.sheet) return;

    const fmtKey = formatSelect.value;
    const formatSpec = PAPER_FORMATS[fmtKey] || PAPER_FORMATS["A4_P"];

    container.style.width = `${formatSpec.canvasWidthPx}px`;

    osmd.setOptions({
      pageFormat: formatSpec.osmdOption
    });

    const measures = parseInt(measuresSelect.value, 10);
    osmd.EngravingRules.RenderXMeasuresPerLineAkaSystem = measures;
    osmd.zoom = parseFloat(scaleSlider.value);

    filterVisiblePart();
    osmd.render();
  }

  // 設定反映ボタン
  btnApplyMeta.addEventListener("click", async () => {
    if (isMidiMode && parsedMidiData) {
      await rebuildMidiXmlAndRender();
    } else {
      await syncMusicXmlAndReload();
    }
    showStatus("スコアとパート設定を更新しました。");
  });

  // 分割基準変更 (MIDI)
  splitModeSelect.addEventListener("change", async () => {
    if (isMidiMode && parsedMidiData) {
      currentParts = Midi2Xml.extractPartProfiles(parsedMidiData, splitModeSelect.value);
      buildPartTable();
      await rebuildMidiXmlAndRender();
    }
  });

  viewModeSelect.addEventListener("change", applyLayoutAndRender);
  formatSelect.addEventListener("change", applyLayoutAndRender);
  measuresSelect.addEventListener("change", applyLayoutAndRender);

  scaleSlider.addEventListener("input", (e) => {
    scaleLabel.textContent = `${Math.round(e.target.value * 100)}%`;
  });
  scaleSlider.addEventListener("change", applyLayoutAndRender);

  quantizeSelect.addEventListener("change", () => {
    if (isMidiMode && parsedMidiData) {
      rebuildMidiXmlAndRender();
    }
  });

  // PDF直接ダウンロード
  async function downloadPdfDirectly() {
    const backends = osmd.drawer && osmd.drawer.Backends;
    if (!backends || backends.length === 0) {
      showStatus("出力対象の楽譜が見つかりません。", true);
      return;
    }

    try {
      btnDownloadPdf.disabled = true;
      showStatus("PDFファイルを生成中...");

      const fmtKey = formatSelect.value;
      const formatSpec = PAPER_FORMATS[fmtKey] || PAPER_FORMATS["A4_P"];
      const orientation = formatSpec.heightMm > formatSpec.widthMm ? "portrait" : "landscape";

      const { jsPDF } = window.jspdf;
      const pdf = new jsPDF({
        orientation: orientation,
        unit: "pt",
        format: [
          (formatSpec.widthMm / 25.4) * 72,
          (formatSpec.heightMm / 25.4) * 72
        ],
        compress: true
      });

      const pdfPageWidth = pdf.internal.pageSize.getWidth();
      const pdfPageHeight = pdf.internal.pageSize.getHeight();

      for (let idx = 0; idx < backends.length; idx++) {
        if (idx > 0) {
          pdf.addPage([pdfPageWidth, pdfPageHeight], orientation);
        }
        showStatus(`PDFを生成中... (${idx + 1} / ${backends.length} ページ)`);

        const svgElement = backends[idx].getSvgElement();
        const vb = svgElement.viewBox && svgElement.viewBox.baseVal;
        const svgW = (vb && vb.width > 0) ? vb.width : (parseFloat(svgElement.getAttribute("width")) || formatSpec.canvasWidthPx);
        const svgH = (vb && vb.height > 0) ? vb.height : (parseFloat(svgElement.getAttribute("height")) || (svgW * 1.414));

        const renderedHeight = pdfPageWidth * (svgH / svgW);
        let targetW = pdfPageWidth;
        let targetH = renderedHeight;
        if (renderedHeight > pdfPageHeight) {
          const ratio = pdfPageHeight / renderedHeight;
          targetW *= ratio;
          targetH = pdfPageHeight;
        }

        await pdf.svg(svgElement, {
          x: 0,
          y: 0,
          width: targetW,
          height: targetH
        });
      }

      const modeName = viewModeSelect.value === "all" ? "FullScore" : `Part_${parseInt(viewModeSelect.value, 10) + 1}`;
      pdf.save(`${currentFileName}_${modeName}.pdf`);
      showStatus(`ダウンロード完了: ${currentFileName}_${modeName}.pdf`);

    } catch (err) {
      console.error(err);
      showStatus(`PDF生成エラー: ${err.message}`, true);
    } finally {
      btnDownloadPdf.disabled = false;
    }
  }

  btnDownloadPdf.addEventListener("click", downloadPdfDirectly);
  btnPrintSheet.addEventListener("click", () => window.print());

  btnExportXml.addEventListener("click", () => {
    if (!currentXmlContent) return;
    const blob = new Blob([currentXmlContent], { type: "application/vnd.recordare.musicxml+xml" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${currentFileName}.musicxml`;
    link.click();
    URL.revokeObjectURL(link);
  });

  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
      handleFile(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", (e) => {
    if (e.target.files.length > 0) {
      handleFile(e.target.files[0]);
    }
  });

  function escapeAttr(str) {
    if (!str) return "";
    return str.replace(/"/g, '&quot;');
  }
});
