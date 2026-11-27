# Production: Contabo VPS (umumiy server)

Server boshqa loyihalar bilan umumiy: nginx 80/443 da (doctr, tabib.today), Docker'da capsula-api (8000) va tablet-today (3001). Contentor ularga tegmaydi:

- alohida compose loyiha `contentor`, papka `/opt/contentor`;
- API faqat `127.0.0.1:8100` da, internetga mavjud nginx orqali chiqadi (`api.contentor.wtf`);
- o'z Postgres va Redis konteynerlari, port ochmaydi;
- worker xotirasi 2 GB bilan cheklangan.

Sayt, admin kabinet va mini ilova Vercel'da (`contentor.wtf`).

Buyruqlarni root sifatida, navbat bilan bajaring. `<...>` joylarga o'z qiymatingizni yozing.

## 0. Oldindan
- DNS: `api` → A yozuv → server IP. Tekshirish: `dig +short api.contentor.wtf` IP'ni ko'rsatsin.
- Lokal bot o'chiq bo'lsin: bitta token bilan bot faqat bitta joyda ishlaydi.

## 1. Swap (serverda yo'q; barcha loyihalar uchun xavfsizlik zaxirasi)
```bash
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
swapon --show
```

## 2. Kod (GitHub deploy key, faqat o'qish)
```bash
ssh-keygen -t ed25519 -C contentor-server -f /root/.ssh/github_contentor -N ""
cat /root/.ssh/github_contentor.pub
```
Chiqqan qatorni GitHub'da qo'shing: **contenter-backend → Settings → Deploy keys → Add deploy key** ("Allow write access" belgilanmasin).
```bash
cat >> /root/.ssh/config <<'EOF'
Host github-contentor
  HostName github.com
  User git
  IdentityFile /root/.ssh/github_contentor
  IdentitiesOnly yes
EOF
mkdir -p /opt/contentor/backups
git clone -b s4/payments github-contentor:Jahongirbek7001/contenter-backend.git /opt/contentor/backend
cd /opt/contentor/backend
```
`github-contentor` taxallusi boshqa loyihalarning GitHub kalitlariga xalal bermaydi.

## 3. Maxfiy sozlamalar
```bash
cd /opt/contentor/backend
cp deploy/production.env.example .env
chmod 600 .env
openssl rand -hex 24
nano .env
```
- `POSTGRES_PASSWORD` va `DATABASE_URL` ichidagi parol bir xil bo'lsin (`openssl` natijasi).
- `GEMINI_API_KEY`, `GCP_PROJECT_ID`, `TELEGRAM_BOT_TOKEN` — lokal `.env` dagi qiymatlar.
- `SUPPORT_CONTACT` — to'lov bo'yicha murojaat uchun Telegram username.
- Payme/Click maydonlari ID'lar kelguncha bo'sh.

Google service account JSON'ni Termius **SFTP** bilan shu nom bilan yuklang: `/opt/contentor/backend/credentials/service-account.json`
```bash
mkdir -p /opt/contentor/backend/credentials
# fayl yuklangandan keyin (konteyner uid 1000 bilan o'qiydi):
chown -R 1000:1000 /opt/contentor/backend/credentials
chmod 700 /opt/contentor/backend/credentials
chmod 600 /opt/contentor/backend/credentials/service-account.json
```

## 4. Ishga tushirish
```bash
cd /opt/contentor/backend
docker compose -f compose.prod.yml up -d --build
docker compose -f compose.prod.yml ps
curl -s http://127.0.0.1:8100/health
```
Birinchi build 5–15 daqiqa. `migrate` — **Exited (0)**, qolganlari — **Up**, `curl` — `{"status":"ok"}`.

## 5. nginx va HTTPS
```bash
cp /opt/contentor/backend/deploy/nginx-api.conf /etc/nginx/sites-available/api.contentor.wtf
ln -s /etc/nginx/sites-available/api.contentor.wtf /etc/nginx/sites-enabled/
nginx -t
systemctl reload nginx
certbot --version || apt install -y certbot python3-certbot-nginx
certbot --nginx -d api.contentor.wtf --redirect
curl -s https://api.contentor.wtf/health
```
`nginx -t` xato bersa, `reload` qilmang — boshqa saytlar ishlashda davom etadi; xatoni menga yuboring.

## 6. Admin akkaunt
```bash
cd /opt/contentor/backend
docker compose -f compose.prod.yml run --rm api python -m scripts.create_admin <email> --role owner
```
Parol bir marta chiqadi — darhol saqlang. Kirish: `https://contentor.wtf/admin`.

## 7. Kundalik backup
```bash
chmod +x /opt/contentor/backend/deploy/backup.sh
/opt/contentor/backend/deploy/backup.sh
(crontab -l 2>/dev/null; echo '30 3 * * * /opt/contentor/backend/deploy/backup.sh >> /opt/contentor/backups/backup.log 2>&1') | crontab -
```

## 8. BotFather
- `/setdomain` → bot → `contentor.wtf`.
- Bot Settings → Menu Button → `https://contentor.wtf/app`.

## Yangilash
```bash
cd /opt/contentor/backend && git pull && docker compose -f compose.prod.yml up -d --build
```

## Foydali buyruqlar
```bash
cd /opt/contentor/backend
docker compose -f compose.prod.yml logs -f --tail 100 worker
docker compose -f compose.prod.yml logs --tail 100 api bot
docker compose -f compose.prod.yml restart bot
docker stats --no-stream
```
