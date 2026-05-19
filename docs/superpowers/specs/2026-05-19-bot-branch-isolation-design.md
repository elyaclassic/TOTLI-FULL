# Bot branch-izolyatsiya — dizayn spetsifikatsiyasi

**Sana:** 2026-05-19
**Holat:** Tasdiqlangan dizayn (implementatsiya kutilmoqda)
**Tier:** C (xavfsizlik-kritik arxitektura)

## 1. Muammo

SENIOR_BOT_GROUP botlari (Yordamchim + 14 ekspert) `claude_client.py` orqali
`claude --dangerously-skip-permissions` ni **`cwd=D:\TOTLI BI`** (jonli prod)
da ishga tushiradi. "X ni qil" deyilsa — jonli fayllar **bevosita** o'zgaradi.
Nusxa/sandbox/tasdiq-darvozasi YO'Q. Yagona himoya — prompt xulqi va inson
intizomi (texnik kafolat emas). Server jonli (har 5 daq yozuv) — xato yoki
noaniq buyruq darhol ishlab chiqarishga ta'sir qiladi.

## 2. Maqsad / Maqsad emas

**Maqsad:**
- Bot kod o'zgarishlarini izolyatsion katalogда qiladi; jonli `D:\TOTLI BI`
  foydalanuvchi tasdiqlamaguncha **o'zgarmaydi** (texnik kafolat, prompt emas).
- Bot jonli kodni o'qiy oladi (tahlil ishlaydi).
- Review + deploy to'liq Telegram orqali (24/7 masofaviy ish).
- Har vazifa alohida branch — granular review/rollback.

**Maqsad EMAS (bu spec qamrovida):**
- DB izolyatsiyasi. DB-ga tegadigan skriptlar (masalan double-count fix)
  hali jonli `totli_holva.db`ga ta'sir qiladi; ular uchun mavjud intizom
  (dry-run + tasdiq) saqlanadi. Prompt buni ogohlantiradi.
- Parallel vazifalar (bitta worktree katalog = ketma-ket).
- Ekspert botlarni texnik read-only qilish (alohida ish; hozir prompt-advisory).

## 3. Arxitektura

Yagona doimiy **git worktree** `D:\TOTLI_BI_botwork` (jonli `D:\TOTLI BI`
bilan `.git` umumiy). `claude_client.py` ish-katalogi shu worktree —
jismoniy kafolat: bot jonli fayllarga yoza olmaydi. Har vazifa shu katalogда
yangi `bot/<sana-slug>` branch. Shared `.git` tufayli branch darhol
`D:\TOTLI BI`da ko'rinadi (review/merge uchun `fetch` shart emas).

Yumshatish (SMB worktree-lock incidentiga qarshi, ref: feedback_git_stash_branch_switch):
worktree **bir marta server2220'da skript orqali** yaratiladi; per-task
faqat branch almashtirish (qayta add/remove yo'q); barcha git amal
server2220-local (ELYOR sharasi worktree katalogiga tegmaydi).

## 4. Komponentlar

### C1 — `scripts/setup_bot_worktree.bat`
- server2220'da Administrator, bir marta. ASCII-only.
- `git -C "D:\TOTLI BI" worktree add "D:\TOTLI_BI_botwork"` (joriy prod
  branch'дан). Idempotent: worktree allaqachon bo'lsa SKIP + xabar.
- Tekshiruv: katalog bor, `.git` fayl ishora qiladi, joriy branch ko'rsatiladi.

### C2 — `claude_client.py` o'zgarishi (eng muhim — fail-closed)
- `CWD` = `D:\TOTLI_BI_botwork` (env `CLAUDE_BOT_CWD` o'rniga shu yo'l
  ustun; yoki konstanta).
- **Fail-closed:** worktree katalogi yo'q yoki `.git` ishora qilmasa →
  `claude` chaqirilmaydi, xato qaytariladi ("izolyatsion muhit yo'q —
  xavfsizlik"). Jonli `D:\TOTLI BI`ga **HECH QACHON** fallback yo'q.
- Jonli o'qish ishlaydi (worktree to'liq checkout).

### C3 — System prompt (experts.py `build_system_prompt`)
Qo'shiladi: "Sen izolyatsion git worktree (`D:\TOTLI_BI_botwork`)dasan.
Jonli `D:\TOTLI BI` tegilmaydi. Kod o'zgartirsang: (1) avval worktree'ni
joriy prod branch HEAD'iga yangila (`git fetch` shart emas — shared
`.git`; `git checkout <prod-branch> && git reset --hard <prod-branch>`
eski bot o'zgarishlari aralashmasin), (2) `git checkout -b
bot/<qisqa-tavsif>`, (3) o'zgartir, (4) commit, (5) branch nomini
foydalanuvchiga ayt. O'zgarish JONLI EMAS — foydalanuvchi `/deploy`
bilan ko'chiradi. DB-ga tegadigan skript HALI jonli DB'ga ta'sir qiladi
— bunday ishда ogohlantir va dry-run taklif et."

**Eslatma (implementatsiya):** worktree'ni prod HEAD'ga yangilash —
ishonchlilik uchun system prompt'ga tayanmaslik kerak; C2/C5 yoki
alohida pre-task qadam buni majburlasin (prompt — qo'shimcha, kafolat
emas). Aniq mexanizm implementatsiya rejasida.

### C4 — `/deploy <branch>` handler (`senior_bot/bot.py`)
- Faqat egasi (`_is_owner`). Format: `/deploy bot/20260519-...`.
- Branch mavjudligini tekshiradi → `scripts/deploy_bot_branch.bat <branch>`
  ni server2220'da yashirin (VBS) ishga tushiradi.
- Natija (C5 hisoboti) egaga DM keladi.
- Ixtiyoriy keyin: `/discard <branch>` (branch o'chirish).

### C5 — `scripts/deploy_bot_branch.bat <branch>`
- server2220, ASCII-only. Qadamlar:
  1. DB backup (`.bak`) — mavjud pattern
  2. `git -C "D:\TOTLI BI" merge --no-ff <branch>` (joriy prod branch'ga)
  3. Konflikt → `git merge --abort`, jonli tegilmadi, xato hisobot, STOP
  4. Server restart (`_server_runner.bat` pattern, kill+start)
  5. Smoke (login + asosiy sahifa, mavjud 15-endpoint pattern)
  6. Telegram egaga: "deploy OK" yoki "FAIL + sabab + rollback"
- Rollback: merge commit `git revert` yoki backup'дан tiklash.

### C6 — Diff-xabar (`claude_client.py` yoki post-hook)
- Vazifa tugagach: agar worktree branch'да prod'дан yangi commit bo'lsa →
  egaga DM: branch nomi + `git diff --stat <prod>..<branch>` + `git log --oneline`.
- Foydalanuvchi shu xabardan `/deploy <branch>` qaror qiladi.

## 5. Hayotiy oqim

```
Telegram "X qil"
  -> Yordamchim (worktree, cwd kafolatlangan):
       worktree -> prod-branch HEAD ga yangilash (toza holat)
       git checkout -b bot/20260519-1230-X
       <kod o'zgartirish> ; git commit
  -> C6: egaga DM (branch + diff --stat prod-branch..bot-branch + log)
Foydalanuvchi diff ko'radi
  -> "/deploy bot/20260519-1230-X"  (C4, faqat egasi)
       -> C5: backup -> merge --no-ff -> restart -> smoke -> DM hisobot
  -> yoki javob bermaydi/"bekor" -> branch turaveradi (jonli 0 ta'sir)
```

## 6. Xato / chekka holatlar

| Holat | Xulq |
|---|---|
| Worktree yo'q | C2 RAD etadi (fail-closed), jonliga fallback YO'Q |
| Deploy merge konflikt | `merge --abort`, jonli o'zgarmaydi, xato DM, STOP |
| Bot branch eskirgan (prod siljigan) | merge konflikt sifatida hisobot, qo'lда hal |
| DB skript so'ralsa | Prompt: ogohlantir, jonli DB ta'sir, dry-run intizom |
| Parallel vazifa | Bitta worktree = ketma-ket; ikkinchisi navbat/ogohlantirish |
| Bekor qilingan branch'lar yig'ilishi | `/discard` (keyin) yoki davriy tozalash |
| Smoke fail deploy'дан keyin | DM ogohlantirish + rollback ko'rsatma |

## 7. Test

- C1 dry-run (worktree allaqachon bor — SKIP).
- C2 fail-closed: worktree yo'q → `claude` chaqirilmasligini tasdiqlash.
- C2 izolyatsiya: worktree'да fayl o'zgartirilsa jonli `D:\TOTLI BI`
  o'zgarmasligini tasdiqlash.
- C5 smoke: deploy'дан keyin login + asosiy sahifa 200.
- C5 merge-konflikt simulyatsiya: jonli tegilmasligini tasdiqlash.

## 8. Rollout / Rollback

- **Rollout (Tier C, tungi oyna yoki nazoratli):** C1 setup → C2/C3 kod →
  C4 handler → C5 skript → standalone bot restart → 1 sinov vazifa →
  `/deploy` test.
- **Rollback:** C2 o'zgarishini qaytarish (bot yana `D:\TOTLI BI`да
  ishlaydi — eski xulq) + worktree o'chirish ixtiyoriy. Bir commit revert.

## 9. Ochiq savollar

Yo'q (4 dizayn qarori tasdiqlangan: qamrov=kod-only, review=Telegram,
branch=per-task, deploy=`/deploy` buyruq).
