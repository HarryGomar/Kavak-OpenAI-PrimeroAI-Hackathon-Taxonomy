from pathlib import Path
root=Path('C:/Users/eduar/Desktop/HACKATON')
p=root/'repo-taxonomy/pipelines/subset/README.md'
body=p.read_text(encoding='utf-8')
body=body.split('## Original Gold subsets, in batches of 500 listings')[0]
section=(root/'tasks/gold-subsets-20261109/corrected-readme-section.md').read_text(encoding='utf-8')
p.write_text(body+section,encoding='utf-8')
