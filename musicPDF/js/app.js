document.addEventListener("DOMContentLoaded", () => {
  const container = document.getElementById("osmd-container");
  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("file-input");
  const statusBar = document.getElementById("status-bar");
  const zoomSelect = document.getElementById("zoom-select");
  const quantizeSelect = document.getElementById("quantize-select");
  const btnExportXml = document.getElementById("btn-export-xml");
  const btnDownloadPdf = document.getElementById("btn-download-pdf");
  const btnPrintSheet = document.getElementById("btn-print-sheet");

  let currentXmlContent = null;
  let currentFileName = "score";
  let lastLoadedFile = null;

  // 画面幅に左右されず厳密にA4用紙サイズ（210mm x 297mm）で組版を行う設定
  const osmd = new opensheetmusicdisplay.OpenSheetMusicDisplay(container, {
    autoResize: false, // 端末の解像度によるページ崩れを防ぎ、同一PDFを保証
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

  // ファイル読み込み
  async function handleFile(file) {
    if (!file) return;
    lastLoadedFile = file;
    currentFileName = file.name.replace(/\.[^/.]+$/, "");
    showStatus(`解析中: ${file.name}`);

    try {
      const ext = file.name.split('.').pop().toLowerCase();

      if (ext === 'mid' || ext === 'midi') {
        const buffer = await file.arrayBuffer();
        const parsedMidi = new Midi(buffer);
        currentXmlContent = Midi2Xml.convert(parsedMidi, {
          quantize: quantizeSelect.value
        });
        await osmd.load(currentXmlContent);

      } else if (ext === 'mxl') {
        const buffer = await file.arrayBuffer();
        await osmd.load(buffer);
        currentXmlContent = null;

      } else {
        // MusicXML 4.0 / 3.x / 一般XML
        let text = await file.text();

        // MusicXML 4.0対策: CORSエラー防止のため外部DOCTYPEを除去
        text = text.replace(/<!DOCTYPE[\s\S]*?>/i, '');
        // 未定義エンティティのエスケープ
        text = text.replace(/&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)/g, '&amp;');

        currentXmlContent = text;

        try {
          await osmd.load(text);
        } catch (parseErr) {
          // 拡張子が .musicxml でも実態が zip (.mxl) だった場合のフォールバック
          const buffer = await file.arrayBuffer();
          await osmd.load(buffer);
          currentXmlContent = null;
        }
      }

      osmd.zoom = parseFloat(zoomSelect.value);
      osmd.render();

      showStatus(`描画完了: ${file.name}`);
      btnExportXml.disabled = !currentXmlContent;
      btnDownloadPdf.disabled = false;
      btnPrintSheet.disabled = false;

    } catch (err) {
      console.error(err);
      showStatus(`読み込みエラー: ${err.message}`, true);
    }
  }

  // 【中核機能】ブラウザ内でSVGから直接A4ベクターPDFを生成してダウンロード
  async function downloadPdfDirectly() {
    const svgs = container.querySelectorAll("svg");
    if (svgs.length === 0) {
      showStatus("出力対象の楽譜が見つかりません。", true);
      return;
    }

    try {
      btnDownloadPdf.disabled = true;
      showStatus("PDFファイルを生成中...");

      const { jsPDF } = window.jspdf;
      const pdf = new jsPDF({
        orientation: "portrait",
        unit: "mm",
        format: "a4",
        compress: true
      });

      const a4Width = pdf.internal.pageSize.getWidth();   // 210mm
      const a4Height = pdf.internal.pageSize.getHeight(); // 297mm

      for (let i = 0; i < svgs.length; i++) {
        if (i > 0) {
          pdf.addPage("a4", "portrait");
        }
        showStatus(`PDFを生成中... (${i + 1} / ${svgs.length} ページ)`);

        const svg = svgs[i];
        // svg2pdf.js を使って各ページのSVGをベクターのままA4に書き込み
        await pdf.svg(svg, {
          x: 0,
          y: 0,
          width: a4Width,
          height: a4Height
        });
      }

      // 直接 .pdf ファイルとして保存
      pdf.save(`${currentFileName}.pdf`);
      showStatus(`ダウンロード完了: ${currentFileName}.pdf`);

    } catch (err) {
      console.error(err);
      showStatus(`PDF生成エラー: ${err.message}`, true);
    } finally {
      btnDownloadPdf.disabled = false;
    }
  }

  // イベントリスナー
  btnDownloadPdf.addEventListener("click", downloadPdfDirectly);

  // 実印刷用
  btnPrintSheet.addEventListener("click", () => {
    window.print();
  });

  // MusicXML保存
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

  // ドラッグ＆ドロップ
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

  // ファイル選択
  fileInput.addEventListener("change", (e) => {
    if (e.target.files.length > 0) {
      handleFile(e.target.files[0]);
    }
  });

  // ズーム変更
  zoomSelect.addEventListener("change", () => {
    osmd.zoom = parseFloat(zoomSelect.value);
    osmd.render();
  });

  // クオンタイズ変更 (MIDIの場合のみ自動再解析)
  quantizeSelect.addEventListener("change", () => {
    if (lastLoadedFile && lastLoadedFile.name.match(/\.midi?$/i)) {
      handleFile(lastLoadedFile);
    }
  });
});
