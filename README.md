# INSTAT Explorer

A small program that reads the Excel tables INSTAT publishes, tidies them up and tells you in plain sentences what is in them. It works in English and in Albanian ([Shqip më poshtë](#shqip)).

INSTAT's spreadsheets are made to be looked at, not to be worked with. Titles are stacked in two languages, years are stored as text (` 01-17`), headers run across merged cells, footnotes sit in the middle of the data and the census tables are old `.xls` files. Getting that into a pivot table, R or Python takes a while. INSTAT Explorer does the tidying and shows you what it decided, so you can check it.

It is meant for schools, universities and offices in Albania, and for anyone else who works with INSTAT numbers. It is free, it runs on an old laptop, it needs no account, and it only goes online when you ask it to fetch something from instat.gov.al.

It is not an INSTAT product and has no connection to them. The data is theirs. Their files say it can be reused if the source is named, and everything this program exports names it.

## What it looks like

Pictures of the program, made by `tools/screenshots.py`; more are in `docs/screenshots/`. The second one shows a real INSTAT table, the others the invented demo data that comes with the program.

![Insights: findings in plain sentences and charts, for a monthly consumer price index](docs/screenshots/02-insights.png)

![How it was read: a real census table of INSTAT with the sheet coloured by role, and the note that 12 sheets, one per prefecture, were combined into one table](docs/screenshots/14-real-xls-how-it-was-read.png)

![The same findings in Albanian, in the dark theme](docs/screenshots/09-albanian-dark.png)

![On a phone: the results come first after a file is opened](docs/screenshots/11-phone-results.png)

## Running it

**Windows 10 or 11, 64-bit.** Get the `.exe` from the Releases page and double-click it. Python is inside, so there is nothing to install. The first start unpacks the program into your user folder and takes about a minute; after that it opens in a few seconds and your browser shows the app. Windows may say it protected your PC because the file is not code-signed (certificates cost money): click More info, then Run anyway. If your computer only accepts signed programs, take the portable zip from the same page instead, unpack it and open `Start-INSTAT-Explorer.bat`.

**In a browser, with nothing to install.** The web version runs the same program inside your browser: upload an Excel or CSV file and read the results. Your files are not sent to any server. It cannot download from instat.gov.al (browsers do not allow it), so download the file from INSTAT's page and upload it. Once GitHub Pages is switched on for the repository it is at `https://<owner>.github.io/<repository>/`; `docs/WEB.md` says how it works and how to host it.

**Anything else.** You need Python 3.11 or newer, 64-bit. From a clone of this repository:

```
python -m pip install .
instat-explorer
```

That installs pandas, numpy and xlrd, the only libraries it uses, and starts the app. A browser tab opens on an address like `http://127.0.0.1:8501/?t=...` that only works on your own computer. Keep the terminal open while you use it and close it to stop the program. `python -m instatkit` does the same as `instat-explorer`, and `instat doctor` checks that the installation works.

## Using it

On the left you choose where the data comes from. You can search for a topic in English or Albanian ("inflation", "papunësia"), paste the link to an INSTAT page or an Excel file, or upload a file you already have. Only the page or file you pick is downloaded, there is no "get everything" button. To just look around, the Demo option opens files with invented numbers, laid out like INSTAT's own.

Every table you open has six tabs:

- Insights: what the table is (how often, which years, which unit), the main figures, findings written as sentences, and charts.
- Explore: pick a measure, some categories and a period range, and see them as lines, bars or a table.
- Clean data: the tidy version, one row per number, or wide with a column per period. Every number carries the cell it came from, like `D7`, so you can check it against INSTAT's file.
- How it was read: the original sheet, coloured by what the program took each part to be (title, header, labels, values, footnotes). If it got something wrong you can correct it there and the table is read again.
- Quality: checks such as whether the regions add up to the national total, plus gaps, duplicates and provisional figures.
- Export: an HTML report that opens offline, CSV, an Excel workbook, a SQLite file, or all of it in one zip.

The button in the top right corner switches the language. It changes the interface, the written findings and the exports. Category names follow too: the program uses the Albanian wording of the file itself when the file has one, and a built-in list of common labels (regions, sexes, age groups, product groups) when it does not. Anything else stays as INSTAT wrote it. The Albanian has not been checked by a native speaker yet. If something reads wrong, please open an issue.

The findings come from fixed rules, not from an AI service, and they only say what the numbers did, never why. They are good for a first read. Check anything you plan to publish against INSTAT's own publication.

## Command line

```
instat                              start the app
instat search papunësia             find a topic (works offline)
instat files inflation              list the Excel files on one topic page
instat process table.xlsx --export html,csv,xlsx
instat inspect table.xlsx           show how a file is read, without exporting
instat demo cpi                     try it on invented numbers
instat doctor                       check the installation
```

Add `--lang sq` to any of them for Albanian, or set `INSTAT_LANG=sq`.

## Good to know

- It has been run over 148 real INSTAT files: every file on 18 topic pages and a sample of the census tables. 144 could be read (4 links no longer work on INSTAT's site) and held 276 tables. In 91 % of them none of the program's own checks failed, and the rest are marked on screen as probably read wrongly.
- A check that passes does not prove a table is right, so the numbers were also compared with 149 figures that INSTAT states in ten of its own press releases. They agree, except one cell in INSTAT's own table; the contributions of groups to inflation are approximate and agree to within 0.02 percentage points (`docs/PUBLISHED_COMPARISON.md`). INSTAT publishes about 640 Excel files and most have not been tried.
- When a file is read wrongly, the How it was read tab shows what happened and lets you correct it, and Export has a "Report a problem" file you can attach to an issue. The method and the numbers are in `docs/EVIDENCE.md`, the known limits in `docs/LIMITATIONS.md`.
- Windows is the only system it has been run on. Nothing in the code is Windows specific, but macOS and Linux are untested.
- INSTAT's statistical database (PxWeb) is not supported, only the Excel and CSV files on the topic pages.
- Tables with very deep headers get generic names for their breakdowns (`category`, `category_2`). The values are right, the names are not always meaningful.
- Inflation contributions are approximate: they use the published weights and ignore chain-linking.

## In a computer lab

- The `.exe` and the portable zip need no administrator rights and no internet. Copy them to the local disk first, not a network drive.
- Downloaded files go to `%LOCALAPPDATA%\INSTAT-Explorer` (portable zip: the `data` folder next to the program; a copy run straight from the source folder: `data` inside it). Set `INSTAT_DATA_DIR` to use another folder. An export you save from the app goes to your browser's download folder; `instat process` writes its exports to the `exports` folder inside the data folder, or to the one you give with `--out`.
- One computer can serve a whole class: start it with `instat-explorer --share` (or `INSTAT-Explorer.exe serve --share`) and the others open the address printed in its window. Whoever has that address can use the program, so keep it inside the room.
- The Windows files are not signed. A policy that only allows signed programs (Smart App Control, AppLocker) will refuse the `.exe` and may refuse the compiled parts of numpy and pandas as well. Ask your IT support to allow the program folder.

## Privacy

Nothing leaves your computer unless you ask for a download. There are no accounts, no analytics and no update checks. The program is a small web server that listens on 127.0.0.1 only, and every request needs a random token that only the link it opens carries, so other people and other web pages on the same computer cannot use it. Spreadsheets are read with size limits, so a broken or hostile file ends in an error message instead of a crash. Uploaded files stay in memory; downloaded files are kept in the data folder, and so are the exports of the command line.

## Development

```
python -m pip install -e ".[dev]"
python -m pytest --cov   # no network or browser needed; about 20 seconds
ruff check .
mypy
bandit -q -c pyproject.toml -r instatkit
python tools/screenshots.py   # drives the program in Edge, Chrome or Chromium and fails on any browser error
python tools/build_web.py --out site && python tools/screenshots.py --web site   # the web version, built and tried in a browser
```

The tests read the sample workbooks of `instatkit/demo.py`, which also return the numbers they wrote, so what the reader recovers can be
compared with the truth cell by cell. `CHANGELOG.md` lists what changed in each version. The release files are made with
`python packaging/build_release.py` (see `docs/DEPLOYMENT.md`); a change to the code reaches the Windows `.exe` and the zips only with the next
release build.

## More documents

`docs/EVIDENCE.md` (what was tested and what it shows), `docs/GALLERY.md` (more pictures), `docs/WEB.md` (the web version), `docs/LIMITATIONS.md`, `docs/SECURITY_AND_PRIVACY.md`, `docs/DEPLOYMENT.md` (for IT and
labs) and `docs/PROPOSAL.md` (a brief for INSTAT and other institutions). `CHANGELOG.md` lists what changed in each version. `python tools/survey.py` repeats the test on
real files; `python tools/screenshots.py` repeats the test in a browser and makes the pictures in `docs/screenshots/`.

## Licence

The code is under the MIT licence (see `LICENSE`). The data is INSTAT's.

---

# Shqip

Një program i vogël që lexon tabelat Excel që boton INSTAT-i, i rregullon dhe të tregon me fjali të thjeshta çfarë ka brenda. Punon në shqip dhe në anglisht.

Tabelat e INSTAT-it janë bërë për t'u parë, jo për t'u përdorur në analiza. Titujt vijnë në dy gjuhë, njëri mbi tjetrin, vitet ruhen si tekst (` 01-17`), kokat e kolonave shtrihen mbi qeliza të bashkuara, shënimet dalin mes të dhënave dhe tabelat e regjistrimit janë skedarë `.xls` të vjetër. Futja e tyre në një pivot table, në R ose në Python kërkon kohë. INSTAT Explorer i rregullon vetë dhe të tregon çfarë ka vendosur, që ta kontrollosh.

Është për shkolla, universitete e zyra në Shqipëri, dhe për këdo tjetër që punon me shifrat e INSTAT-it. Është falas, punon edhe në laptop të vjetër, nuk kërkon llogari dhe lidhet me internetin vetëm kur i kërkon të sjellë diçka nga instat.gov.al.

Nuk është produkt i INSTAT-it dhe nuk ka lidhje me të. Të dhënat janë të tyre. Skedarët e tyre thonë se mund të ripërdoren nëse përmendet burimi, dhe çdo gjë që eksporton programi e përmend.

## Si nis

**Windows 10 ose 11, 64-bit.** Merr skedarin `.exe` nga faqja Releases dhe hape me dy klikime. Python është brenda, ndaj nuk ka asgjë për të instaluar. Herën e parë programi shpaketohet në dosjen tënde të përdoruesit dhe zgjat rreth një minutë; më pas hapet për pak sekonda dhe shfletuesi të shfaq aplikacionin. Windows mund të thotë se të ka mbrojtur kompjuterin, sepse skedari nuk është i nënshkruar (certifikatat kushtojnë para): kliko More info, pastaj Run anyway. Nëse kompjuteri pranon vetëm programe të nënshkruara, merr zip-in portativ nga e njëjta faqe, shpaketoje dhe hap `Start-INSTAT-Explorer.bat`.

**Në shfletues, pa instaluar asgjë.** Versioni në ueb e ekzekuton të njëjtin program brenda shfletuesit: ngarko një skedar Excel ose CSV dhe lexo rezultatet. Skedarët e tu nuk dërgohen në asnjë server. Nuk mund të shkarkojë nga instat.gov.al (shfletuesit nuk e lejojnë), ndaj shkarkoje skedarin nga faqja e INSTAT-it dhe ngarkoje. Pasi të aktivizohet GitHub Pages për repozitorin, ai ndodhet te `https://<pronari>.github.io/<repozitori>/`; `docs/WEB.md` (në anglisht) shpjegon si punon dhe si vihet në një server.

**Çdo sistem tjetër.** Të duhet Python 3.11 ose më i ri, 64-bit. Nga një kopje e këtij repozitori:

```
python -m pip install .
instat-explorer
```

Kjo instalon pandas, numpy dhe xlrd, të vetmet biblioteka që përdor, dhe nis aplikacionin. Në shfletues hapet një adresë si `http://127.0.0.1:8501/?t=...` që punon vetëm në kompjuterin tënd. Mbaje terminalin të hapur sa kohë e përdor dhe mbylle për ta ndalur programin. `python -m instatkit` bën të njëjtën gjë si `instat-explorer`, dhe me `instat doctor` kontrollon nëse instalimi punon.

## Si përdoret

Në të majtë zgjedh nga i merr të dhënat. Mund të kërkosh një temë në shqip ose në anglisht ("çmimet", "papunësia"), të ngjitësh lidhjen e një faqeje ose të një skedari Excel të INSTAT-it, ose të ngarkosh një skedar që e ke tashmë. Shkarkohet vetëm faqja ose skedari që zgjedh ti; nuk ka buton "merr gjithçka". Për të parë si funksionon pa asnjë skedar, opsioni Shembull hap skedarë me numra të shpikur, të ndërtuar si tabelat e INSTAT-it.

Çdo tabelë ka gjashtë skeda:

- Përmbledhja: çfarë është tabela (sa shpesh, cilët vite, cila njësi), shifrat kryesore, gjetjet e shkruara si fjali dhe grafikët.
- Eksploro: zgjedh një tregues, disa kategori dhe një interval kohor, dhe i sheh si vija, shirita ose tabelë.
- Të dhënat e pastruara: versioni i rregulluar, një rresht për çdo numër, ose me një kolonë për çdo periudhë. Çdo numër mban qelizën nga vjen, p.sh. `D7`, që ta kontrollosh me skedarin e INSTAT-it.
- Si u lexua: fleta origjinale, e ngjyrosur sipas asaj që programi mori për çdo pjesë (titull, kre, etiketa, vlera, shënime). Nëse e ka gabim, e korrigjon aty dhe tabela lexohet përsëri.
- Cilësia: kontrolle si "a mblidhen rajonet në totalin kombëtar", plus boshllëqe, dublikime dhe shifra të përkohshme.
- Eksporto: raport HTML që hapet pa internet, CSV, libër pune Excel, skedar SQLite, ose gjithçka në një zip.

Butoni lart djathtas ndërron gjuhën. Ndryshon ndërfaqen, gjetjet e shkruara dhe eksportet. Edhe emrat e kategorive ndjekin gjuhën: programi përdor fjalët shqip që ka vetë skedari kur i ka, dhe një listë të brendshme etiketash të zakonshme (rajonet, gjinitë, grupmoshat, grupet e produkteve) kur nuk i ka. Gjithçka tjetër mbetet siç e ka shkruar INSTAT-i. Shqipja nuk është kontrolluar ende nga një folës amtar. Nëse diçka tingëllon gabim, hap një issue.

Gjetjet vijnë nga rregulla të fiksuara, jo nga një shërbim inteligjence artificiale, dhe thonë vetëm çfarë bënë numrat, kurrë pse. Janë të mira për një lexim të parë. Atë që do ta botosh kontrolloje me botimin e vetë INSTAT-it.

## Komandat

```
instat                              nis aplikacionin
instat search papunësia             gjen një temë (punon pa internet)
instat files inflation              liston skedarët Excel të një faqeje teme
instat process table.xlsx --export html,csv,xlsx
instat inspect table.xlsx           tregon si lexohet një skedar, pa eksportuar
instat demo cpi                     provo me numra të shpikur
instat doctor                       kontrollon instalimin
```

Shto `--lang sq` te cilado prej tyre për shqip, ose vendos `INSTAT_LANG=sq`.

## Çfarë duhet ditur

- Është ekzekutuar mbi 148 skedarë të vërtetë të INSTAT-it: çdo skedar i 18 faqeve të temave dhe një mostër e tabelave të regjistrimit. 144 u lexuan (4 lidhje nuk punojnë më në faqen e INSTAT-it) dhe dhanë 276 tabela. Në 91 % të tyre asnjë nga kontrollet e vetë programit nuk dështoi, ndërsa të tjerat shënohen në ekran si ndoshta të lexuara gabim.
- Një kontroll i kaluar nuk provon se një tabelë është e saktë, ndaj numrat u krahasuan edhe me 149 shifra që vetë INSTAT-i jep në dhjetë komunikata të veta për shtyp. Ato përputhen, me përjashtim të një qelize në tabelën e vetë INSTAT-it; kontributet e grupeve në inflacion janë të përafërta dhe përputhen brenda 0,02 pikë përqindjeje (`docs/PUBLISHED_COMPARISON.md`). INSTAT-i boton rreth 640 skedarë Excel dhe shumica nuk janë provuar.
- Kur një skedar lexohet gabim, skeda Si u lexua tregon çfarë ndodhi dhe të lejon ta korrigjosh, dhe te Eksporto ka një skedar "Raporto një problem" që mund ta bashkëngjitësh te një issue. Metoda dhe numrat janë te `docs/EVIDENCE.md`, kufizimet e njohura te `docs/LIMITATIONS.md` (në anglisht).
- Vetëm në Windows është provuar. Në kod nuk ka asgjë të veçantë për Windows, por macOS dhe Linux nuk janë provuar.
- Baza statistikore e INSTAT-it (PxWeb) nuk mbështetet, vetëm skedarët Excel dhe CSV në faqet e temave.
- Tabelat me koka shumë të shtresuara marrin emra të përgjithshëm për ndarjet (`category`, `category_2`). Vlerat janë të sakta, emrat jo gjithmonë kuptimplotë.
- Kontributet e inflacionit janë të përafërta: përdorin peshat e publikuara dhe nuk marrin parasysh zinxhirimin.

## Në një laborator kompjuterik

- `.exe` dhe zip-i portativ nuk kërkojnë të drejta administratori dhe as internet. Kopjoji më parë në diskun lokal, jo në një disk rrjeti.
- Skedarët e shkarkuar shkojnë te `%LOCALAPPDATA%\INSTAT-Explorer` (zip-i portativ: dosja `data` pranë programit; kur e nis drejtpërdrejt nga dosja e kodit burimor: `data` brenda saj). Me `INSTAT_DATA_DIR` zgjedh një dosje tjetër. Një eksport që ruan nga aplikacioni shkon te dosja e shkarkimeve e shfletuesit; `instat process` i shkruan eksportet te nëndosja `exports` e dosjes së të dhënave, ose te ajo që jep me `--out`.
- Një kompjuter mund t'i shërbejë gjithë klasës: nise me `instat-explorer --share` (ose `INSTAT-Explorer.exe serve --share`) dhe të tjerët hapin adresën që shfaqet në dritaren e tij. Kushdo që e ka atë adresë mund ta përdorë programin, ndaj mbaje brenda klasës.
- Skedarët për Windows nuk janë të nënshkruar. Një politikë që lejon vetëm programe të nënshkruara (Smart App Control, AppLocker) do ta refuzojë `.exe` dhe mund të refuzojë edhe pjesët e përpiluara të numpy dhe pandas. Kërkoji mbështetjes teknike që ta lejojë dosjen e programit.

## Privatësia

Asgjë nuk del nga kompjuteri yt nëse nuk kërkon një shkarkim. Nuk ka llogari, analitikë apo kontrolle për përditësime. Programi është një server i vogël web që dëgjon vetëm te 127.0.0.1, dhe çdo kërkesë ka nevojë për një çelës të rastësishëm që e mban vetëm lidhja që hap programi, ndaj njerëzit e tjerë dhe faqet e tjera web në të njëjtin kompjuter nuk mund ta përdorin. Fletët e punës lexohen me kufij përmasash, kështu që një skedar i prishur ose keqdashës përfundon me një mesazh gabimi, jo me një rrëzim. Skedarët e ngarkuar mbeten në memorie; ata të shkarkuar ruhen në dosjen e të dhënave, ashtu si eksportet e komandës.

## Licenca

Kodi është nën licencën MIT (shih `LICENSE`). Të dhënat janë të INSTAT-it.
