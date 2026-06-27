# Tools

自作ツール  
ほとんどLLM作  
Base64のやつ(base64.html)以外  

[一覧](https://arurion.github.io/Tools/index_all.html)

自作疑似フルート関数生成.jsは結構考えました。関数音源作成ツールで使えます  

Polyglot.htmlはDavid Buchanan氏のpack.pyをもとにつくった

---  

## ライセンス (License)

本リポジトリ内の成果物は、以下の例外を除き、すべて **MIT License** のもとで公開されています。

### 例外 (Exceptions)

- **GPLv3 適用ファイル**
  以下のファイルは **FFmpeg (GPL構成)** に依存または由来しているため、本プロジェクトにおいて **GNU GPLv3** を適用して配布します。
  - `画像・映像系ツール/数式画像変換ΛΔ.html`
  - `画像・映像系ツール/TDNFFmpeg.html`
  - `ffmpeg/ffmpeg-core.js`
  - `ffmpeg/ffmpeg-core.wasm`
  ※ `ffmpeg-core.*` の上流ライセンスは GPLv2 or later ですが、本プロジェクトでは GPLv3 を選択しています。

- **FFmpeg.wasm ラッパー（ffmpeg/ ディレクトリ内の一部）**
  以下のファイルは `@ffmpeg/ffmpeg` 由来であり、**MIT License** が適用されます。
  - `ffmpeg/ffmpeg.js`
  - `ffmpeg/814.ffmpeg.js`
  - `ffmpeg/util.js`
