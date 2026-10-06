# QR Chaos — Internet Edition

This version does **not** require everyone to be on the same Wi-Fi.

- Host opens one public Admin URL.
- Admin displays one QR code.
- Players scan it using their own mobile data or any internet connection.
- Players enter their names and play individually.
- Host sees live players and leaderboard.
- No extra QR codes are used.

## Local test

```bash
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000/` for the player page.
For local admin testing, set an admin key and open `/admin/<key>`:

PowerShell:

```powershell
$env:ADMIN_KEY="test123"
python app.py
```

Then open:

```text
http://localhost:5000/admin/test123
```

## Deploy publicly with Render

Render's current Flask deployment flow uses a Python web service, `pip install -r requirements.txt` as the build command, and Gunicorn as the production server. Free web services can be used, but they can spin down after inactivity. For an event, open the Admin page before players arrive and keep it active. See the official Render docs: https://render.com/docs/deploy-flask

### Easiest method

1. Create a GitHub repository.
2. Upload this entire folder to the repository.
3. In Render, choose **New → Web Service** and connect the repository.
4. Runtime: **Python 3**.
5. Build command:
   `pip install -r requirements.txt`
6. Start command:
   `gunicorn app:app --workers 1 --threads 8 --timeout 0`
7. Deploy.
8. Render gives you a public `https://...onrender.com` address.
9. Open the service URL followed by `/admin/<your-admin-key>`.
10. Put that Admin page on the projector/screen.
11. Players scan the ONE QR shown there.

If using the included `render.yaml` Blueprint, Render can use the included build/start settings and generate `SECRET_KEY` and `ADMIN_KEY` environment variables.

## Important

SQLite is intentionally kept single-instance for this simple event game. The Render start command uses one Gunicorn worker so all players share the same in-memory/process state and SQLite database. If you later need persistent history across deploys or multiple server instances, move the player/game state to PostgreSQL.
