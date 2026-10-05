# INSTAT Explorer

A small program that reads the Excel tables INSTAT publishes, tidies them up and tells you in plain sentences what is in them. It works in English and in Albanian ([Shqip më poshtë](#shqip)).

INSTAT's spreadsheets are made to be looked at, not to be worked with. Titles are stacked in two languages, years are stored as text (` 01-17`), headers run across merged cells, footnotes sit in the middle of the data and the census tables are old `.xls` files. Getting that into a pivot table, R or Python takes a while. INSTAT Explorer does the tidying and shows you what it decided, so you can check it.

It is meant for schools, universities and offices in Albania, and for anyone else who works with INSTAT numbers. It is free, it runs on an old laptop, it needs no account, and it only goes online when you ask it to fetch something from instat.gov.al.

It is not an INSTAT product and has no connection to them. The data is theirs. Their files say it can be reused if the source is named, and everything this program exports names it.

## Running it

**Windows 10 or 11, 64-bit.** Get the `.exe` from the Releases page and double-click it. Python is inside, so there is nothing to install. The first start unpacks the program into your user folder and takes about a minute; after that it opens in a few seconds and your browser shows the app. Windows may say it protected your PC because the file is not code-signed (certificates cost money): click More info, then Run anyway. If your computer only accepts signed programs, take the portable zip from the same page instead, unpack it and open `Start-INSTAT-Explorer.bat`.

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

- It has been tried on 52 real census tables and on six real files from other topics (consumer prices, labour force survey, national accounts, foreign trade, population, tourism). INSTAT publishes about 640 Excel files and most of them have not been tried. When a file is read wrongly, the How it was read tab shows what happened, and Export has a Report a problem file you can attach to an issue.
- Windows is the only system it has been run on. Nothing in the code is Windows specific, but macOS and Linux are untested.
- INSTAT's statistical database (PxWeb) is not supported, only the Excel and CSV files on the topic pages.
- Tables with very deep headers get generic names for their breakdowns (`category`, `category_2`). The values are right, the names are not always meaningful.
- Inflation contributions are approximate: they use the published weights and ignore chain-linking.

## In a computer lab

- The `.exe` and the portable zip need no administrator rights and no internet. Copy them to the local disk first, not a network drive.
- Downloaded files and exports go to `%LOCALAPPDATA%\INSTAT-Explorer` (portable zip: the `data` folder next to the program). Set `INSTAT_DATA_DIR` to use another folder.
- One computer can serve a whole class: start it with `instat-explorer --share` (or `INSTAT-Explorer.exe serve --share`) and the others open the address printed in its window. Whoever has that address can use the program, so keep it inside the room.
- The Windows files are not signed. A policy that only allows signed programs (Smart App Control, AppLocker) will refuse the `.exe` and may refuse the compiled parts of numpy and pandas as well. Ask your IT support to allow the program folder.

## Privacy

Nothing leaves your computer unless you ask for a download. There are no accounts, no analytics and no update checks. The program is a small web server that listens on 127.0.0.1 only, and every request needs a random token that only the link it opens carries, so other people and other web pages on the same computer cannot use it. Spreadsheets are read with size limits, so a broken or hostile file ends in an error message instead of a crash. Uploaded files stay in memory; downloaded files and exports are kept in the data folder.

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

- Është provuar në 52 tabela të vërteta të regjistrimit dhe në gjashtë skedarë të vërtetë nga tema të tjera (çmimet e konsumit, anketa e forcave të punës, llogaritë kombëtare, tregtia e jashtme, popullsia, turizmi). INSTAT-i boton rreth 640 skedarë Excel dhe shumica nuk janë provuar. Kur një skedar lexohet gabim, skeda Si u lexua tregon çfarë ndodhi, dhe te Eksporto ka një skedar "Raporto një problem" që mund ta bashkëngjitësh te një issue.
- Vetëm në Windows është provuar. Në kod nuk ka asgjë të veçantë për Windows, por macOS dhe Linux nuk janë provuar.
- Baza statistikore e INSTAT-it (PxWeb) nuk mbështetet, vetëm skedarët Excel dhe CSV në faqet e temave.
- Tabelat me koka shumë të shtresuara marrin emra të përgjithshëm për ndarjet (`category`, `category_2`). Vlerat janë të sakta, emrat jo gjithmonë kuptimplotë.
- Kontributet e inflacionit janë të përafërta: përdorin peshat e publikuara dhe nuk marrin parasysh zinxhirimin.

## Në një laborator kompjuterik

- `.exe` dhe zip-i portativ nuk kërkojnë të drejta administratori dhe as internet. Kopjoji më parë në diskun lokal, jo në një disk rrjeti.
- Skedarët e shkarkuar dhe eksportet shkojnë te `%LOCALAPPDATA%\INSTAT-Explorer` (zip-i portativ: dosja `data` pranë programit). Me `INSTAT_DATA_DIR` zgjedh një dosje tjetër.
- Një kompjuter mund t'i shërbejë gjithë klasës: nise me `instat-explorer --share` (ose `INSTAT-Explorer.exe serve --share`) dhe të tjerët hapin adresën që shfaqet në dritaren e tij. Kushdo që e ka atë adresë mund ta përdorë programin, ndaj mbaje brenda klasës.
- Skedarët për Windows nuk janë të nënshkruar. Një politikë që lejon vetëm programe të nënshkruara (Smart App Control, AppLocker) do ta refuzojë `.exe` dhe mund të refuzojë edhe pjesët e përpiluara të numpy dhe pandas. Kërkoji mbështetjes teknike që ta lejojë dosjen e programit.

## Privatësia

Asgjë nuk del nga kompjuteri yt nëse nuk kërkon një shkarkim. Nuk ka llogari, analitikë apo kontrolle për përditësime. Programi është një server i vogël web që dëgjon vetëm te 127.0.0.1, dhe çdo kërkesë ka nevojë për një çelës të rastësishëm që e mban vetëm lidhja që hap programi, ndaj njerëzit e tjerë dhe faqet e tjera web në të njëjtin kompjuter nuk mund ta përdorin. Fletët e punës lexohen me kufij përmasash, kështu që një skedar i prishur ose keqdashës përfundon me një mesazh gabimi, jo me një rrëzim. Skedarët e ngarkuar mbeten në memorie; ata të shkarkuar dhe eksportet ruhen në dosjen e të dhënave.

## Licenca

Kodi është nën licencën MIT (shih `LICENSE`). Të dhënat janë të INSTAT-it.
