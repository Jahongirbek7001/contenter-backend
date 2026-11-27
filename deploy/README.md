# Production: Contabo VPS

Serverda bitta `docker compose` ishlaydi: **Caddy** (HTTPS) → **api**, hamda **bot**, **worker**, **postgres**, **redis**. Sayt, admin kabinet va mini ilova Vercel'da (`contentor.wtf`), API esa shu serverda (`api.contentor.wtf`).

Buyruqlarni Termius'da navbat bilan bajaring. `<...>` joylarga o'z qiymatingizni yozing.

---

## 0. Oldindan

- Domen registratorida **`api` uchun A yozuv** → server IP. Tekshirish (kompyuteringizda): `nslookup api.contentor.wtf` IP'ni ko'rsatishi kerak.
- Lokal bot o'chiq bo'lsin: bitta token bilan bot faqat bitta joyda ishlay oladi.

## 1. Alohida foydalanuvchi (root ostida ishlamaymiz)

Termius'da Contabo bergan root bilan kiring:

```bash
adduser deploy                       # parol so'raydi — kuchli parol qo'ying (sudo uchun)
usermod -aG sudo deploy
id deploy                            # uid=1000 bo'lishi kerak; boshqa raqam chiqsa, menga ayting
```

SSH kalitni `deploy` ga ko'chiring:

```bash
mkdir -p /home/deploy/.ssh
cp /root/.ssh/authorized_keys /home/deploy/.ssh/
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh && chmod 600 /home/deploy/.ssh/authorized_keys
```

> Root'ga parol bilan kirgan bo'lsangiz, `/root/.ssh/authorized_keys` bo'lmaydi. Unda Termius'da: **Keychain → kalitingiz → Export to Host** → `deploy` foydalanuvchisini tanlang.

Termius'da **yangi host** yarating: `deploy@<IP>`, shu kalit bilan. **Yangi oynada kirib ko'ring.** Kirish ishlagandan keyingina 2-qadamga o'ting, root oynasini yopmang.

## 2. SSH'ni yopish (parol va root kirishi o'chadi)

`deploy` oynasida:

```bash
sudo tee /etc/ssh/sshd_config.d/10-contentor.conf >/dev/null <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
EOF
sudo sshd -t && sudo systemctl restart ssh
```

Yana bir yangi oynada `deploy@<IP>` bilan kirib ko'ring. Ishlasa, root oynasini yopsangiz bo'ladi.

## 3. Tizim: yangilanish, firewall, swap, vaqt zonasi

```bash
sudo apt update && sudo apt -y upgrade
sudo apt -y install ufw fail2ban unattended-upgrades git
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 443
sudo ufw --force enable
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
sudo timedatectl set-timezone Asia/Tashkent
```

## 4. Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker deploy
exit
```

Qayta kiring (guruh o'zgarishi kuchga kirishi uchun) va tekshiring: `docker run --rm hello-world`.

## 5. Kod (GitHub deploy key, faqat o'qish)

```bash
ssh-keygen -t ed25519 -C contentor-server -f ~/.ssh/github_backend -N ""
cat ~/.ssh/github_backend.pub
```

Chiqqan qatorni GitHub'da qo'shing: **contenter-backend → Settings → Deploy keys → Add deploy key**, "Allow write access" belgilanmasin.

```bash
cat >> ~/.ssh/config <<'EOF'
Host github.com
  IdentityFile ~/.ssh/github_backend
  IdentitiesOnly yes
EOF
sudo mkdir -p /opt/contentor && sudo chown deploy:deploy /opt/contentor
git clone -b s4/payments git@github.com:Jahongirbek7001/contenter-backend.git /opt/contentor/backend
cd /opt/contentor/backend
```

> PR'lar `main` ga merge bo'lgach: `git switch main && git pull`.

## 6. Maxfiy sozlamalar

```bash
cp deploy/production.env.example .env
chmod 600 .env
openssl rand -hex 24          # baza paroli — nusxa oling
nano .env
```

- `POSTGRES_PASSWORD` va `DATABASE_URL` ichidagi parol **bir xil** bo'lsin (yuqoridagi `openssl` natijasi).
- `GEMINI_API_KEY`, `GCP_PROJECT_ID`, `TELEGRAM_BOT_TOKEN` — lokal `.env` dagi qiymatlar.
- `SUPPORT_CONTACT` — to'lov bo'yicha murojaat uchun Telegram username (masalan `@contentor_support`).
- Payme/Click maydonlari ID'lar kelguncha bo'sh qoladi.

Google service account JSON: Termius **SFTP** bilan kompyuteringizdagi `backend/credentials/` ichidagi faylni serverga yuklang, nomi aynan shunday bo'lsin:

```
/opt/contentor/backend/credentials/service-account.json
```

```bash
chmod 700 credentials && chmod 600 credentials/service-account.json
```

## 7. Ishga tushirish

```bash
docker compose -f compose.prod.yml up -d --build
docker compose -f compose.prod.yml ps
```

Birinchi build 5–10 daqiqa oladi. `migrate` **exited (0)**, qolganlari **running** bo'lishi kerak. Keyin:

```bash
curl https://api.contentor.wtf/health          # {"status":"ok"}
docker compose -f compose.prod.yml logs --tail 50 api bot worker
```

`curl` sertifikat xatosi bersa, DNS hali yetib bormagan: `docker compose -f compose.prod.yml logs caddy`.

## 8. Admin akkaunt

```bash
docker compose -f compose.prod.yml run --rm api python -m scripts.create_admin <email> --role owner
```

Parol **bir marta** chiqadi: darhol parol menejeriga saqlang. Kirish: `https://contentor.wtf/admin`.

## 9. Kundalik backup

```bash
chmod +x deploy/backup.sh
deploy/backup.sh                                   # bir marta qo'lda sinang
(crontab -l 2>/dev/null; echo '30 3 * * * /opt/contentor/backend/deploy/backup.sh >> /opt/contentor/backups/backup.log 2>&1') | crontab -
```

Dump'lar `/opt/contentor/backups` da 14 kun turadi. Server tashqarisiga nusxa (rclone → bulut) keyingi bosqichda sozlanadi.

## 10. BotFather

- `/setdomain` → botni tanlang → `contentor.wtf` (saytda Telegram orqali kirish uchun).
- `/mybots` → bot → **Bot Settings → Menu Button** → `https://contentor.wtf/app` (mini ilova).

## Yangilash (yangi kod chiqqanda)

```bash
cd /opt/contentor/backend
git pull
docker compose -f compose.prod.yml up -d --build
```

Migratsiyalar `migrate` xizmatida avtomatik qo'llanadi.

## Foydali buyruqlar

```bash
docker compose -f compose.prod.yml logs -f worker          # generatsiyalarni kuzatish
docker compose -f compose.prod.yml restart bot
docker compose -f compose.prod.yml exec postgres psql -U contentor
docker stats --no-stream                                  # xotira va CPU
```

Backup'dan tiklash (ehtiyot bo'ling, joriy bazani almashtiradi):

```bash
docker compose -f compose.prod.yml exec -T postgres pg_restore -U contentor -d contentor --clean --if-exists < /opt/contentor/backups/<fayl>.dump
```
