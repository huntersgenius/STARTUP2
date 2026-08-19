# Edge server — installation

**Who this is for:** the clinic's IT-responsible person, or anyone comfortable
plugging in a computer. You do not need to be an engineer.

**Time:** about 40 minutes, most of it waiting for downloads.

**You need:** the mini-PC, a monitor, a keyboard, a network cable, and the
`.env` file the SihhatAI team sent you.

---

## 1. Plug it in

Connect the mini-PC to power, to the monitor and keyboard, and to the clinic's
router with the network cable. Turn it on.

Wi-Fi also works, but the cable is more reliable and this box does not move.

## 2. Log in

Username and password are on the sticker underneath the box.

## 3. Copy the settings file

Put the `.env` file the team sent you into the folder `/opt/sihhatai/`.
If you received it on a USB stick:

```
cp /media/usb/.env /opt/sihhatai/.env
```

Check it arrived:

```
ls -l /opt/sihhatai/.env
```

You should see one line ending in `.env`. If you see "No such file", the copy
did not work — try again before continuing.

## 4. Start the system

```
cd /opt/sihhatai
sudo docker compose up -d
```

The first start downloads about 6 GB and takes 20–30 minutes on a normal
clinic connection. You can leave it running and come back.

## 5. Check it is working

```
curl http://localhost:8000/health
```

You should see `"status":"ok"`. If you see `"degraded"`, wait five minutes and
try again — the database may still be starting.

## 6. Find the box's address

```
hostname -I
```

Write down the first number, for example `192.168.1.50`. **The tablets need
this number.** Write it on the sticker on the box as well, so nobody has to
find it again.

## 7. Connect a tablet

On each tablet, open SihhatAI → Settings → Server address, and type:

```
http://192.168.1.50:8000
```

(using the number from step 6). Tap Save, then Test connection. It should say
connected.

## 8. Done

The system starts automatically whenever the box is powered on. You do not need
to do anything after a power cut except make sure the box is switched on.

---

## If something is wrong

**The tablets say "no connection".**
Check the box is on and the network cable is plugged in at both ends. Then run
`sudo docker compose ps` — every line should say `running`. If one says
`exited`, run `sudo docker compose up -d` again.

**"No space left on device".**
Run `sudo docker system prune -a` and then `sudo docker compose up -d`.

**Everything else.**
Run this and send the output to the SihhatAI team:

```
sudo docker compose logs --tail 200 > /tmp/sihhat-logs.txt
```

Support: +998 XX XXX XX XX (working hours), support@sihhat.uz

---

## For the SihhatAI team

- Backups: `pg_dump` runs nightly into `./backups`, kept 14 days. Restore is
  documented in `docs/PILOT_RUNBOOK.md` and is tested before each pilot.
- The box holds no cloud API keys by design: it runs the local model only, so
  a stolen mini-PC cannot spend the API budget.
- `PII_ENCRYPTION_KEY` is per clinic. Losing it makes that clinic's records
  permanently unreadable — it belongs in the ops password manager before the
  box ships, not after.
