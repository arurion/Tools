import os

# 除外したいディレクトリやファイル名
EXCLUDE_DIRS = {'.git', '.github', '__pycache__', 'node_modules'}
EXCLUDE_FILES = {'generate_index.py', 'index_all.html'}

def generate_html():
    html_content = """
    <!DOCTYPE html>
    <html lang="ja">
    <head>
        <meta charset="UTF-8">
        <title>Repository Explorer</title>
        <style>
            body { font-family: sans-serif; line-height: 1.6; padding: 20px; background: #f9f9f9; }
            ul { list-style-type: none; }
            li { margin: 5px 0; }
            .dir { font-weight: bold; color: #d9534f; }
            .file { color: #0275d8; text-decoration: none; }
            .file:hover { text-decoration: underline; }
            .container { background: white; padding: 20px; border-radius: 8px; border: 1px solid #ddd; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>File Explorer</h1>
            <ul>
    """

    for root, dirs, files in os.walk('.'):
        # 除外設定
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        
        level = root.replace('.', '').count(os.sep)
        indent = '    ' * level
        rel_path = os.path.relpath(root, '.')
        
        if rel_path != '.':
            html_content += f'{indent}<li><span class="dir">📁 {os.path.basename(root)}/</span><ul>\n'
        
        for f in sorted(files):
            if f in EXCLUDE_FILES or f.startswith('.'):
                continue
            f_path = os.path.join(rel_path, f) if rel_path != '.' else f
            html_content += f'{indent}    <li><a class="file" href="{f_path}">📄 {f}</a></li>\n'
            
        if rel_path != '.':
            html_content += f'{indent}</ul></li>\n'

    html_content += """
            </ul>
        </div>
    </body>
    </html>
    """
    
    with open('index_all.html', 'w', encoding='utf-8') as f:
        f.write(html_content)

if __name__ == "__main__":
    generate_html()
