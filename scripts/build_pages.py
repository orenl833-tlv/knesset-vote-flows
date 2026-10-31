"""Copy the built night site (out/site_live) into docs/ for GitHub Pages.

The page source has no document skeleton: claude.ai adds one when it hosts the page. Pages serves the file as it is,
so add the doctype, charset and viewport here; without them a phone renders the page at desktop width.
"""
import os
import shutil

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SRC, DOCS = os.path.join(ROOT, 'out/site_live'), os.path.join(ROOT, 'docs')

HEAD = ('<!doctype html>\n<html lang="he" dir="rtl">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n')


def main():
    shutil.rmtree(DOCS, ignore_errors=True)
    shutil.copytree(SRC, DOCS)
    open(os.path.join(DOCS, '.nojekyll'), 'w').close()  # serve every file as is, no Jekyll build
    page = os.path.join(DOCS, 'index.html')
    body = open(page, encoding='utf-8').read()
    # the source opens with its <title>, <meta> and <link> tags, then <style>: those go in <head>, the rest in <body>
    cut = body.index('<style')
    cut = body.index('</style>', cut) + len('</style>')
    open(page, 'w', encoding='utf-8').write(HEAD + body[:cut] + '\n</head>\n<body>\n' + body[cut:] + '\n</body>\n</html>\n')
    print('pages site ready:', DOCS)


if __name__ == '__main__':
    main()
