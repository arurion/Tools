import os
import urllib.parse
import html

# --- 設定：除外リストの徹底 ---
EXCLUDE_DIRS = {'.git', '.github', '__pycache__', 'node_modules', '.venv', '.vscode'}
EXCLUDE_FILES = {'generate_index.py', 'index_all.html', '.gitignore', 'package-lock.json'}

def generate_tree(dir_path, level=0):
    """再帰的にディレクトリツリーを走査し、正しい入れ子構造のHTMLリストを生成する"""
    html_lines = []
    indent = "    " * (level + 2)

    try:
        # OSや環境による差異をなくすためソート
        entries = sorted(os.listdir(dir_path))
    except PermissionError:
        return []

    dirs = []
    files = []
    
    for entry in entries:
        if entry.startswith('.') or entry in EXCLUDE_DIRS or entry in EXCLUDE_FILES:
            continue
        full_path = os.path.join(dir_path, entry)
        if os.path.isdir(full_path):
            dirs.append(entry)
        else:
            files.append(entry)

    # ディレクトリの処理（再帰的に子要素の <ul> を開閉する）
    for d in dirs:
        d_name = html.escape(d)
        html_lines.append(f"{indent}<li><span class='dir-name'>{d_name}/</span>")
        html_lines.append(f"{indent}    <ul>")
        
        # サブディレクトリ内を再帰処理
        html_lines.extend(generate_tree(os.path.join(dir_path, d), level + 2))
        
        # バグ修正：ここで確実にタグを閉じる
        html_lines.append(f"{indent}    </ul>")
        html_lines.append(f"{indent}</li>")

    # ファイルの処理
    for f in files:
        full_path = os.path.join(dir_path, f)
        rel_path = os.path.relpath(full_path, '.')
        # OS依存のパス区切りを URL用の "/" に統一
        url_path = rel_path.replace(os.sep, '/')
        
        # urllib.parse.quote はデフォルトで safe='/' ですが、明記しておくとより安全です
        encoded_url = urllib.parse.quote(url_path, safe='/')
        safe_f_name = html.escape(f)
        
        html_lines.append(f"{indent}<li><a class='file-link' href='./{encoded_url}'>{safe_f_name}</a></li>")

    return html_lines

def generate_html():
    html_content = [
        "<!DOCTYPE html>",
        "<html lang='ja'>",
        "<head>",
        "    <meta charset='UTF-8'>",
        "    <meta name='viewport' content='width=device-width, initial-scale=1.0'>",
        "    <title>Repository Explorer (2026 Stable)</title>",
        "    <style>",
        "        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; padding: 20px; background: #f4f7f9; color: #333; }",
        "        .container { max-width: 900px; margin: 0 auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }",
        "        h1 { border-bottom: 2px solid #007bff; padding-bottom: 10px; color: #007bff; font-size: 24px; }",
        "        ul { list-style: none; padding-left: 20px; }",
        "        li { margin: 8px 0; position: relative; }",
        "        .dir-name { font-weight: bold; color: #e67e22; cursor: default; }",
        "        .dir-name::before { content: '📁 '; }",
        "        .file-link { color: #2980b9; text-decoration: none; transition: color 0.2s; }",
        "        .file-link:hover { color: #3498db; text-decoration: underline; }",
        "        .file-link::before { content: '📄 '; }",
        "        .footer { margin-top: 30px; font-size: 0.8em; color: #7f8c8d; text-align: right; }",
        "    </style>",
        "</head>",
        "<body>",
        "    <div class='container'>",
        "        <h1>Repository File Explorer</h1>",
        "        <ul>"
    ]

    # カレントディレクトリ起点でツリーを生成して結合
    html_content.extend(generate_tree('.'))

    html_content.append("        </ul>")
    html_content.append("        <div class='footer'>Generated at: 2026-05-17 (Version 2026.1)</div>")
    html_content.append("    </div>")
    html_content.append("</body>")
    html_content.append("</html>")

    with open('index_all.html', 'w', encoding='utf-8') as f:
        f.write("\n".join(html_content))

if __name__ == "__main__":
    generate_html()
