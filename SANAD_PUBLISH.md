# SANAD PUBLISH V1 — staging preview
Standalone preview, does not modify OpenMontage rendering or post automatically.

## Start in Codespaces
From the existing OpenMontage checkout:
```sh
git fetch origin sanad-publish-v1
git show origin/sanad-publish-v1:sanad_publish.py > /tmp/sanad_publish.py
python3 /tmp/sanad_publish.py
```
In Ports, forward 8765 and make only this port Public if permitted by the workspace. Never make a general editor or terminal port public. Open the URL printed by the service. Keep the random upload token private. Choose an approved H.264 MP4 up to 100 MiB. The output is an expiring six-hour bearer URL, not a public listing. Uploads are stored outside the repository. Do not put tokens or footage in Git.

## Connector handoff
- Instagram: pass the HTTPS MP4 URL to the connected publishing connector, with approved caption.
- YouTube: pass URL, title, description, audience declaration and visibility.
- LinkedIn personal profile, TikTok, Snapchat, Facebook and X: require authorized publishing integrations; no simulated posting.
- Log returned post ID/URL only on confirmed success. Never retry blindly.
- Keep Codespaces running while platforms retrieve the asset. Test from an unauthenticated browser first.
- No new paid service or automatic external publishing.
- Current storage persists on the Codespace; URLs expire, but files remain on disk. No automatic deletion.
- Production deployment needs durable HTTPS object storage, quota controls, persistent authentication and connector authorization. This preview is not production hardened.
