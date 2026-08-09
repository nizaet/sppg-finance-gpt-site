# SPPG Finance Legacy UI Railway v7.5

Deploy:
```bash
BASE="/Users/zaetjd/Library/CloudStorage/GoogleDrive-jack7bear@gmail.com/My Drive/akuntan gpt"

cd "$BASE"

unzip -o "SPPG_Finance_Legacy_UI_Railway_v7_5.zip"

rsync -av --delete \
  --exclude=".git" \
  --exclude="node_modules" \
  --exclude="dist" \
  sppg-finance-legacy-ui-railway-v7_5/ \
  sppg-finance-railway-ready/

cd "$BASE/sppg-finance-railway-ready"

rm -rf node_modules dist
npm install
npm run build

git add -A
git commit -m "Improve dashboard reports audit backup and excel export v7.5"
git push
```
