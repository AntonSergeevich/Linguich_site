# -*- coding: utf-8 -*-
"""Банки вопросов теста уровня — по одному на язык.

Тест был один на всю школу и спрашивал по-английски, какой бы язык человек
ни выбирал: вопросов с привязкой к языку просто не существовало, а движок
подставлял «общие». Для школы с семью языками это выглядело так, будто
остальных шесть не существует.

Здесь стартовые наборы. Их писал разработчик, а не преподаватель школы:
задания намеренно простые и однозначные, без тонкостей, где можно спорить
о верном варианте. Преподаватель каждого языка должен их просмотреть и
дополнить — вопросы редактируются в админке, для этого код не нужен.

Потолок банка честно показывается человеку: если по языку заведены только
A1–A2, тест так и скажет, что выше уровень подтвердит преподаватель.
Врать «ваш уровень A2» тому, кто читает B2, нельзя.

Формат строки: (уровень, навык, вопрос, подсказка, варианты, номер верного, пояснение)
"""

from .models import Skill

G, V, R, U = Skill.GRAMMAR, Skill.VOCABULARY, Skill.READING, Skill.USAGE


GERMAN = [
    # ---------------- A1 ----------------
    ("A1", G, "Ich ____ Studentin.", "", ["bin", "bist", "ist", "sind"], 0, "ich → bin."),
    ("A1", G, "Das ist ____ Buch.", "Das Buch — средний род.", ["eine", "einen", "ein", "einem"], 2, ""),
    ("A1", V, "Das Gegenteil von «groß» ist ____.", "", ["klein", "alt", "kalt", "neu"], 0, ""),
    ("A1", U, "— Wie heißt du? — ____", "", ["Ich bin gut.", "Ich heiße Anna.", "Es geht.", "Danke schön."], 1, ""),
    ("A1", V, "Montag, Dienstag, ____, Donnerstag.", "", ["Freitag", "Sonntag", "Mittwoch", "Samstag"], 2, ""),
    # ---------------- A2 ----------------
    ("A2", G, "Gestern ____ ich ins Kino gegangen.", "Perfekt с глаголом движения.",
     ["habe", "bin", "war", "werde"], 1, "gehen образует Perfekt с sein."),
    ("A2", G, "Ich helfe ____ Bruder.", "helfen требует Dativ.",
     ["meinen", "mein", "meinem", "meines"], 2, ""),
    ("A2", G, "Er ist ____ als ich.", "", ["groß", "größer", "am größten", "mehr groß"], 1, ""),
    ("A2", V, "Ich freue mich ____ das Wochenende.", "", ["über", "auf", "für", "an"], 1,
     "sich freuen auf — о будущем."),
    ("A2", U, "Im Restaurant sagt man: «____, bitte!»", "", ["Die Rechnung", "Das Geld", "Die Karte", "Der Preis"], 0, ""),
    # ---------------- B1 ----------------
    ("B1", G, "Wenn ich Zeit hätte, ____ ich mitkommen.", "Konjunktiv II.",
     ["werde", "würde", "wurde", "will"], 1, ""),
    ("B1", G, "Der Film, ____ wir gestern gesehen haben, war gut.", "Akkusativ, мужской род.",
     ["der", "dem", "den", "das"], 2, ""),
    ("B1", G, "Das Haus wurde 1990 ____.", "Passiv.", ["baute", "gebaut", "bauen", "baut"], 1, ""),
    ("B1", V, "Er hat den Termin ____, weil er krank war.", "",
     ["abgesagt", "angesagt", "gesagt", "aufgesagt"], 0, ""),
    ("B1", R, "«Das Museum ist täglich außer montags geöffnet.» Wann ist es geschlossen?",
     "", ["Am Sonntag", "Am Montag", "Jeden Tag", "Nie"], 1, ""),
]


FRENCH = [
    # ---------------- A1 ----------------
    ("A1", G, "Je ____ étudiant.", "", ["es", "suis", "est", "sommes"], 1, ""),
    ("A1", G, "Il y a ____ livre sur la table.", "", ["un", "une", "des", "de la"], 0, "livre — мужской род."),
    ("A1", V, "Le contraire de «grand» est ____.", "", ["petit", "vieux", "froid", "long"], 0, ""),
    ("A1", U, "— Comment tu t'appelles ? — ____", "",
     ["J'ai vingt ans.", "Je m'appelle Marie.", "Ça va bien.", "Il fait beau."], 1, ""),
    ("A1", V, "lundi, mardi, ____, jeudi.", "", ["vendredi", "dimanche", "mercredi", "samedi"], 2, ""),
    # ---------------- A2 ----------------
    ("A2", G, "Hier, j'____ mangé au restaurant.", "Passé composé.", ["ai", "suis", "as", "est"], 0, ""),
    ("A2", G, "Je vais ____ Paris demain.", "", ["en", "au", "à", "dans"], 2, "к городу — à."),
    ("A2", G, "Elle est plus grande ____ moi.", "", ["de", "que", "comme", "à"], 1, ""),
    ("A2", V, "Il fait froid, mets ton ____.", "", ["manteau", "chapeau", "parapluie", "sac"], 0, ""),
    ("A2", U, "Au magasin : «____ coûte ce livre ?»", "", ["Combien", "Comment", "Quand", "Pourquoi"], 0, ""),
    # ---------------- B1 ----------------
    ("B1", G, "Si j'avais de l'argent, je ____ en voyage.", "Условное второго типа.",
     ["pars", "partirai", "partirais", "suis parti"], 2, ""),
    ("B1", G, "C'est le livre ____ je t'ai parlé.", "", ["que", "qui", "dont", "où"], 2,
     "parler de → dont."),
    ("B1", G, "Il faut que tu ____ tout de suite.", "Subjonctif.",
     ["viens", "viennes", "viendras", "venir"], 1, ""),
    ("B1", V, "Le film a été ____ en 2010.", "", ["tourné", "tourner", "tournant", "tourne"], 0, ""),
    ("B1", R, "«Le musée est ouvert tous les jours sauf le mardi.» Quel jour est-il fermé ?",
     "", ["Le lundi", "Le mardi", "Le dimanche", "Jamais"], 1, ""),
]


CHINESE = [
    # ---------------- A1 ----------------
    ("A1", V, "«你好» значит:", "", ["Спасибо", "Здравствуйте", "До свидания", "Извините"], 1, ""),
    ("A1", G, "我 ____ 学生。", "«Я — студент».", ["有", "在", "是", "去"], 2, "是 — связка «быть»."),
    ("A1", U, "— 谢谢! — ____", "", ["对不起", "不客气", "再见", "你好"], 1, "«Не за что»."),
    ("A1", V, "Число «три» записывается:", "", ["二", "三", "四", "五"], 1, ""),
    ("A1", V, "«水» значит:", "", ["огонь", "вода", "гора", "человек"], 1, ""),
    # ---------------- A2 ----------------
    ("A2", G, "我昨天 ____ 北京。", "Действие в прошлом.", ["去了", "去", "会去", "要去"], 0, ""),
    ("A2", G, "一 ____ 书", "Счётное слово для книги.", ["个", "本", "只", "张"], 1, ""),
    ("A2", G, "他比我 ____ 。", "Сравнение: «он выше меня».", ["高", "很高", "最高", "高了"], 0,
     "После 比 прилагательное идёт без 很."),
    ("A2", G, "你会说汉语 ____ ?", "Общий вопрос.", ["吗", "呢", "吧", "了"], 0, ""),
    ("A2", V, "«便宜» значит:", "", ["дорогой", "дешёвый", "быстрый", "красивый"], 1, ""),
]


KOREAN = [
    # ---------------- A1 ----------------
    ("A1", V, "«안녕하세요» значит:", "", ["Спасибо", "Здравствуйте", "Извините", "До свидания"], 1, ""),
    ("A1", G, "저는 학생 ____ .", "«Я студент».", ["이에요", "예요", "이다", "있어요"], 0,
     "После согласной — 이에요."),
    ("A1", U, "— 감사합니다. — ____", "", ["아니에요", "안녕히 가세요", "죄송합니다", "네, 맞아요"], 0, ""),
    ("A1", V, "Число «три» по-корейски (исконный счёт):", "", ["하나", "둘", "셋", "넷"], 2, ""),
    ("A1", V, "«물» значит:", "", ["вода", "огонь", "хлеб", "дом"], 0, ""),
    # ---------------- A2 ----------------
    ("A2", G, "어제 영화를 ____ .", "Прошедшее время.", ["봐요", "봤어요", "볼 거예요", "보세요"], 1, ""),
    ("A2", G, "학교 ____ 가요.", "Направление движения.", ["에서", "에", "은", "도"], 1, ""),
    ("A2", G, "밥을 먹 ____ 물을 마셔요.", "«Поел и попил».", ["고", "지만", "서", "면"], 0, ""),
    ("A2", V, "«비싸다» значит:", "", ["дешёвый", "дорогой", "вкусный", "далёкий"], 1, ""),
    ("A2", U, "В кафе просят счёт: «____ 주세요.»", "", ["계산서", "메뉴", "물", "숟가락"], 0, ""),
]


TURKISH = [
    # ---------------- A1 ----------------
    ("A1", V, "«Merhaba» значит:", "", ["Спасибо", "Здравствуйте", "Пожалуйста", "Пока"], 1, ""),
    ("A1", G, "Ben öğrenci ____ .", "«Я студент».", ["yim", "sin", "dir", "im"], 3, ""),
    ("A1", V, "Противоположность «büyük» — ____.", "", ["küçük", "uzun", "yeni", "sıcak"], 0, ""),
    ("A1", U, "— Teşekkür ederim. — ____", "", ["Rica ederim", "Görüşürüz", "Affedersiniz", "Merhaba"], 0, ""),
    ("A1", V, "Число «üç» — это:", "", ["два", "три", "четыре", "пять"], 1, ""),
    # ---------------- A2 ----------------
    ("A2", G, "Dün sinemaya ____ .", "Прошедшее время.", ["gidiyorum", "gittim", "giderim", "gideceğim"], 1, ""),
    ("A2", G, "Okul ____ geliyorum.", "«Иду из школы».", ["a", "da", "dan", "ın"], 2, ""),
    ("A2", G, "Bu kitap benim ____ .", "Принадлежность.", ["kitabım", "kitap", "kitaba", "kitabı"], 0, ""),
    ("A2", V, "«ucuz» значит:", "", ["дорогой", "дешёвый", "быстрый", "тёплый"], 1, ""),
    ("A2", U, "В ресторане: «____, lütfen.»", "", ["Hesap", "Kapı", "Yol", "Saat"], 0, "«Счёт, пожалуйста»."),
    # ---------------- B1 ----------------
    ("B1", G, "Yarın hava güzel ____ , pikniğe gideriz.", "Условие.",
     ["olursa", "oldu", "oluyor", "olacak"], 0, ""),
    ("B1", G, "Bu ev 1990'da ____ .", "Пассив.", ["yaptı", "yapıldı", "yapıyor", "yapacak"], 1, ""),
    ("B1", V, "Toplantıyı ____ , çünkü hastaydı.", "", ["iptal etti", "kabul etti", "devam etti", "başladı"], 0, ""),
    ("B1", R, "«Müze pazartesi hariç her gün açıktır.» Müze ne zaman kapalı?",
     "", ["Pazar", "Pazartesi", "Cumartesi", "Hiçbir zaman"], 1, ""),
]


CZECH = [
    # ---------------- A1 ----------------
    ("A1", V, "«Dobrý den» значит:", "", ["Спасибо", "Добрый день", "До свидания", "Извините"], 1, ""),
    ("A1", G, "Já ____ student.", "", ["jsem", "jsi", "je", "jsou"], 0, ""),
    ("A1", V, "Opak slova «velký» je ____.", "", ["malý", "starý", "nový", "dlouhý"], 0, ""),
    ("A1", U, "— Děkuji. — ____", "", ["Prosím", "Na shledanou", "Promiňte", "Dobrý den"], 0, ""),
    ("A1", V, "pondělí, úterý, ____, čtvrtek.", "", ["pátek", "neděle", "středa", "sobota"], 2, ""),
    # ---------------- A2 ----------------
    ("A2", G, "Včera jsem ____ do kina.", "Прошедшее время, мужской род.",
     ["jdu", "šel", "půjdu", "jít"], 1, ""),
    ("A2", G, "Bydlím ____ Praze.", "", ["do", "na", "v", "z"], 2, ""),
    ("A2", G, "Je ____ než já.", "Сравнение.", ["vysoký", "vyšší", "nejvyšší", "více vysoký"], 1, ""),
    ("A2", V, "«levný» значит:", "", ["дорогой", "дешёвый", "быстрый", "тёплый"], 1, ""),
    ("A2", U, "V restauraci: «____, prosím.»", "", ["Účet", "Dveře", "Cesta", "Hodiny"], 0, ""),
    # ---------------- B1 ----------------
    ("B1", G, "Kdybych měl čas, ____ bych s tebou.", "Условное наклонение.",
     ["jdu", "šel", "půjdu", "jít"], 1, ""),
    ("B1", G, "Ten film, ____ jsme viděli včera, byl dobrý.", "",
     ["který", "kterého", "kterým", "kterém"], 0, ""),
    ("B1", G, "Ten dům byl ____ v roce 1990.", "Пассив.",
     ["postavil", "postaven", "stavět", "staví"], 1, ""),
    ("B1", R, "«Muzeum je otevřeno každý den kromě pondělí.» Kdy je zavřeno?",
     "", ["V neděli", "V pondělí", "V sobotu", "Nikdy"], 1, ""),
]


# Ключ — slug языка из каталога школы. Языка нет в каталоге — банк просто
# не загрузится, ошибки не будет: список языков ведёт школа, а не код.
BANKS = {
    "german": GERMAN,
    "french": FRENCH,
    "chinese": CHINESE,
    "korean": KOREAN,
    "turkish": TURKISH,
    "czech": CZECH,
}
