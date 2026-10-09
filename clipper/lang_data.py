"""Per-language word lists and templates for the parts that read or write
words: funny-word ranking, swear censoring, title/hashtag ideas, Whisper's
hint prompt and the style editor's sample caption.

Languages without an entry fall back to English lists (laughs like "hahaha"
and chat emotes work everywhere, and the AI judge writes titles in any
language). To add a language, copy the "en" block.
"""

from __future__ import annotations

# Whisper language codes offered in the Subtitles tab (native names)
SPOKEN = {
    "Türkçe": "tr", "English": "en", "Español": "es", "Português": "pt",
    "Deutsch": "de", "Français": "fr", "Italiano": "it", "Polski": "pl",
    "Русский": "ru", "Українська": "uk", "العربية": "ar", "Nederlands": "nl",
    "Svenska": "sv", "Norsk": "no", "Dansk": "da", "Suomi": "fi",
    "Čeština": "cs", "Română": "ro", "Magyar": "hu", "Ελληνικά": "el",
    "Azərbaycanca": "az", "Қазақша": "kk", "فارسی": "fa", "עברית": "he",
    "हिन्दी": "hi", "Bahasa Indonesia": "id", "Tiếng Việt": "vi", "ไทย": "th",
    "Filipino": "tl", "日本語": "ja", "한국어": "ko", "中文": "zh",
    "Auto-detect": None,
}

# languages written without spaces between words
NO_SPACES = {"ja", "zh", "th", "lo", "my", "km"}

DATA: dict[str, dict] = {
    "en": {
        "reaction": {"omg", "wtf", "bruh", "nooo", "dead", "crying", "insane", "yooo",
                     "lmao", "lmfao", "bro", "dude", "help"},
        "weak": {"no", "what", "why", "wait", "stop", "run", "come", "yo", "oh", "wow",
                 "man", "guys", "chat"},
        "phrases": ["oh my god", "what the", "no way", "are you serious", "i'm dead",
                    "i can't", "let's go", "what was that", "are you kidding",
                    "bro what", "i'm crying", "get out"],
        "swear_exact": {"fuck", "fucking", "fucked", "shit", "shitty", "bitch", "ass",
                        "asshole", "dick", "cunt", "bastard", "damn", "wtf", "fck"},
        "swear_prefix": ("fuck", "motherf", "bullshit", "dumbass", "jackass"),
        "titles": {
            "laugh": ["I couldn't stop laughing 😂", "This laugh is contagious 😂",
                      "Crying laughing at this 😂"],
            "scream": ["My heart stopped 😱", "I've never screamed like this 😱",
                       "Did NOT expect that 😱"],
            "chat": ["Chat lost it 😂", "Chat was right 💀", "Chat called it 😂"],
            "loud": ["Did not see that coming 😳", "It happened so fast 😳",
                     "What just happened 💀"],
            "any": ["Wait for the end… 💀", "Best moment of the stream 🔥",
                    "This moment is legendary 🔥"],
            "game": ["This happened in {game} {e}", "{game} did me dirty {e}",
                     "Only in {game} {e}"],
        },
        "hashtags": ["#funny", "#gaming", "#fyp", "#viral", "#streamer", "#clips"],
        "laugh_tag": "#lol",
        "post_heads": ("TITLE IDEAS", "HASHTAGS", "COPY-PASTE"),
        "prompt": "Hey guys, welcome back to the stream! Oh my god, what the hell? "
                  "No way, bro. Hahaha, that's insane!",
        "sample": "Oh my god, what was that! Is this a joke?",
    },
    "tr": {
        "reaction": {"öldüm", "ölüyorum", "öleceğim", "bittim", "koptum", "oha", "yuh",
                     "eyvah", "imdat", "inanmıyorum", "inanamıyorum", "inanılmaz",
                     "allahım", "rezil", "rezalet", "napıyorsun", "naptın", "noluyor",
                     "nooluyor", "ağladım", "gülmekten", "çıldırdım", "delirdim",
                     "korktum", "yapma"},
        "weak": {"lan", "abi", "kanka", "kardeşim", "hayır", "dur", "kaç", "koş", "ayy",
                 "aa", "aaa", "of", "off", "offf", "hadi", "ciddi", "şaka", "kalbim",
                 "anne", "yardım", "vay"},
        "phrases": ["yok artık", "ne oluyor", "ne oldu", "ne yapıyorsun", "ne yaptın",
                    "aman allahım", "ya allah", "ciddi misin", "şaka mı", "ben öldüm",
                    "gülmekten öldüm", "ne alaka", "olamaz", "allah allah", "vay be"],
        "swear_exact": {"am", "amk", "amq", "aq", "mk", "mq", "oç", "oc", "piç", "pic",
                        "sik", "göt", "götü", "götün", "götünü", "götüne", "puşt", "sg"},
        "swear_prefix": ("amına", "amina", "amcık", "amcik", "sikiş", "sikis", "sikt",
                         "siker", "sikey", "sikik", "sikim", "sikin", "sikle", "yarrak",
                         "yarram", "yarak", "orospu", "pezevenk", "kahpe", "gavat",
                         "götveren", "ibne", "kaltak"),
        "titles": {
            "laugh": ["Gülmekten öldüm 😂", "Kendimi tutamadım 😂", "Bu kahkaha bulaşıcı 😂"],
            "scream": ["Kalbim durdu 😱", "Çığlığı duyan koştu 😱", "Böyle korkmadım 😱"],
            "chat": ["Chat bunu görünce koptu 😂", "Chat haklıymış 💀",
                     "Chat ne dediyse o oldu 😂"],
            "loud": ["Bunu beklemiyordum 😳", "Bir anda oldu 😳", "Ne olduğunu anlamadım 💀"],
            "any": ["Sonunu bekle… 💀", "Yayının en iyi anı 😂", "Bu an efsane 🔥"],
            "game": ["{game} oynarken bu oldu {e}", "{game}'da işler karıştı {e}",
                     "{game} bize bunu yaşattı {e}"],
        },
        "hashtags": ["#keşfet", "#komik", "#keşfetbeniöneçıkar", "#yayın", "#oyun",
                     "#gaming", "#fyp", "#viral"],
        "laugh_tag": "#komikanlar",
        "platform": {"kick": ["#kickturkiye"], "twitch": ["#twitchturkiye"]},
        "post_heads": ("BAŞLIK ÖNERİLERİ", "ETİKETLER", "KOPYALA-YAPIŞTIR"),
        "prompt": "Selam arkadaşlar, yayına hoş geldiniz! Hadi başlayalım. "
                  "Oha, amına koyim, ne oluyor lan? Siktir git ya, öldüm! Hahaha, "
                  "kanka bak, ne yapıyorsun oğlum?",
        "sample": "Oha amına koyim, bu ne ya! İnanılmaz şaka mı?",
    },
    "es": {
        "reaction": {"increíble", "brutal", "morí", "muerto", "muerta",
                     "socorro", "ayuda", "noo", "flipando",
                     "flipo", "alucino", "locura"},
        "weak": {"no", "qué", "dios", "madre", "wey", "tío", "tía", "bro", "hermano", "espera", "corre", "vamos", "oye",
                 "mira", "ay", "uf", "venga"},
        "phrases": ["dios mío", "madre mía", "no puede ser", "qué fue eso", "qué pasó",
                    "estás de broma", "me muero", "no me jodas", "qué demonios",
                    "ni de broma", "qué locura", "me meo"],
        "swear_exact": {"puta", "puto", "mierda", "joder", "coño", "cabrón", "cabron",
                        "pendejo", "pendeja", "carajo", "verga", "culero", "hostia",
                        "chingada", "gilipollas", "imbécil"},
        "swear_prefix": ("hijueputa", "hijodeputa", "chinga", "pinche", "jodid",
                         "putada", "mierd"),
        "titles": {
            "laugh": ["No podía parar de reír 😂", "Esta risa es contagiosa 😂",
                      "Me muero de risa 😂"],
            "scream": ["Casi me da algo 😱", "Nunca grité así 😱", "No me lo esperaba 😱"],
            "chat": ["El chat se volvió loco 😂", "El chat tenía razón 💀",
                     "El chat lo sabía 😂"],
            "loud": ["No vi venir eso 😳", "Pasó todo muy rápido 😳",
                     "¿Qué acaba de pasar? 💀"],
            "any": ["Espera al final… 💀", "El mejor momento del directo 🔥",
                    "Momento legendario 🔥"],
            "game": ["Esto pasó en {game} {e}", "{game} me la jugó {e}",
                     "Solo en {game} {e}"],
        },
        "hashtags": ["#humor", "#gaming", "#fyp", "#viral", "#streamer", "#parati",
                     "#clips"],
        "laugh_tag": "#risas",
        "post_heads": ("IDEAS DE TÍTULO", "HASHTAGS", "COPIAR Y PEGAR"),
        "prompt": "¡Hola chicos, bienvenidos al directo! Madre mía, ¿qué demonios? "
                  "No puede ser, tío. ¡Jajaja, qué locura!",
        "sample": "¡Madre mía, qué fue eso! ¿Es una broma?",
    },
    "pt": {
        "reaction": {"socorro", "morri", "morrendo", "caraca", "inacreditável", "absurdo", "chorei", "surreal"},
        "weak": {"não", "meu", "deus", "nossa", "mano", "cara", "velho", "espera", "corre", "vai", "olha", "ai", "uai",
                 "bora", "gente"},
        "phrases": ["meu deus", "não acredito", "o que foi isso", "tá de brincadeira",
                    "que isso", "morri de rir", "não pode ser", "que porra",
                    "puta que pariu", "ai meu deus"],
        "swear_exact": {"porra", "caralho", "merda", "foda", "puta", "buceta", "fdp",
                        "krl", "pqp", "cacete", "viado", "corno", "otário"},
        "swear_prefix": ("fodid", "fode", "arrombad", "desgraç", "caralh"),
        "titles": {
            "laugh": ["Não consegui parar de rir 😂", "Essa risada é contagiante 😂",
                      "Morri de rir 😂"],
            "scream": ["Meu coração parou 😱", "Nunca gritei assim 😱",
                       "Não esperava por essa 😱"],
            "chat": ["O chat surtou 😂", "O chat tinha razão 💀", "O chat avisou 😂"],
            "loud": ["Não vi isso vindo 😳", "Foi tudo muito rápido 😳",
                     "O que acabou de acontecer? 💀"],
            "any": ["Espera o final… 💀", "Melhor momento da live 🔥",
                    "Momento lendário 🔥"],
            "game": ["Isso aconteceu no {game} {e}", "{game} me trollou {e}",
                     "Só no {game} {e}"],
        },
        "hashtags": ["#humor", "#gaming", "#fyp", "#viral", "#streamer", "#foryou",
                     "#clips"],
        "laugh_tag": "#kkkk",
        "post_heads": ("IDEIAS DE TÍTULO", "HASHTAGS", "COPIAR E COLAR"),
        "prompt": "Fala galera, bem-vindos à live! Meu Deus, que porra é essa? "
                  "Não acredito, mano. Kkkkk, que absurdo!",
        "sample": "Meu Deus, o que foi isso! É brincadeira?",
    },
    "de": {
        "reaction": {"krass", "alter", "digga", "hilfe", "unglaublich", "wahnsinn",
                     "geil", "lol", "omg", "nein", "tot", "heftig", "brutal"},
        "weak": {"nee", "warte", "stopp", "lauf", "komm", "jungs", "leute", "oh", "boah",
                 "mann", "chat"},
        "phrases": ["oh mein gott", "was zum", "das gibt's doch nicht", "ist nicht dein ernst",
                    "was war das", "ich kann nicht mehr", "ich sterbe", "auf keinen fall",
                    "was ist passiert", "ich lache mich tot"],
        "swear_exact": {"scheiße", "scheisse", "scheiß", "scheiss", "fick", "ficken",
                        "fickt", "arschloch", "arsch", "hurensohn", "wichser", "fotze",
                        "kacke", "verdammt", "missgeburt", "spast"},
        "swear_prefix": ("verfickt", "hurens", "scheiß", "scheiss", "wichs"),
        "titles": {
            "laugh": ["Ich konnte nicht aufhören zu lachen 😂", "Dieses Lachen ist ansteckend 😂",
                      "Ich lag am Boden 😂"],
            "scream": ["Mir ist das Herz stehen geblieben 😱", "So hab ich noch nie geschrien 😱",
                       "Damit hab ich NICHT gerechnet 😱"],
            "chat": ["Der Chat ist eskaliert 😂", "Der Chat hatte recht 💀",
                     "Der Chat hat's gewusst 😂"],
            "loud": ["Das kam aus dem Nichts 😳", "Das ging so schnell 😳",
                     "Was ist da gerade passiert 💀"],
            "any": ["Wartet aufs Ende… 💀", "Bester Moment des Streams 🔥",
                    "Legendärer Moment 🔥"],
            "game": ["Das ist in {game} passiert {e}", "{game} hat mich fertig gemacht {e}",
                     "Nur in {game} {e}"],
        },
        "hashtags": ["#lustig", "#gaming", "#fyp", "#viral", "#streamer", "#fürdich",
                     "#clips"],
        "laugh_tag": "#lachen",
        "post_heads": ("TITELIDEEN", "HASHTAGS", "KOPIEREN & EINFÜGEN"),
        "prompt": "Hey Leute, willkommen im Stream! Oh mein Gott, was zur Hölle? "
                  "Alter, das gibt's doch nicht. Hahaha, wie krass!",
        "sample": "Oh mein Gott, was war das! Ist das ein Witz?",
    },
    "fr": {
        "reaction": {"mdr", "ptdr", "jpp", "incroyable", "dingue", "ouf", "mort", "morte",
                     "sérieux", "wesh", "aide", "nooon", "fou", "folie"},
        "weak": {"non", "attends", "cours", "viens", "allez", "frère", "frérot", "mec",
                 "les", "gars", "oh", "bah"},
        "phrases": ["oh mon dieu", "c'est quoi ça", "c'est pas possible", "tu rigoles",
                    "je suis mort", "j'en peux plus", "qu'est-ce qui se passe",
                    "mais non", "c'est une blague", "je meurs"],
        "swear_exact": {"putain", "merde", "connard", "connasse", "salope", "enculé",
                        "encule", "pute", "bordel", "nique", "niquer", "batard", "bâtard",
                        "con", "conne", "fdp", "ntm"},
        "swear_prefix": ("enculé", "nique", "fils de p"),
        "titles": {
            "laugh": ["Je n'arrivais plus à m'arrêter de rire 😂", "Ce rire est contagieux 😂",
                      "J'en pleure de rire 😂"],
            "scream": ["Mon cœur s'est arrêté 😱", "Jamais crié comme ça 😱",
                       "Je ne m'y attendais PAS 😱"],
            "chat": ["Le chat a pété un plomb 😂", "Le chat avait raison 💀",
                     "Le chat l'avait dit 😂"],
            "loud": ["Je ne l'ai pas vu venir 😳", "Tout est allé si vite 😳",
                     "Qu'est-ce qui vient de se passer 💀"],
            "any": ["Attends la fin… 💀", "Meilleur moment du live 🔥",
                    "Moment légendaire 🔥"],
            "game": ["C'est arrivé sur {game} {e}", "{game} m'a trahi {e}",
                     "Seulement sur {game} {e}"],
        },
        "hashtags": ["#drole", "#gaming", "#fyp", "#viral", "#streamer", "#pourtoi",
                     "#clips"],
        "laugh_tag": "#mdr",
        "post_heads": ("IDÉES DE TITRE", "HASHTAGS", "COPIER-COLLER"),
        "prompt": "Salut tout le monde, bienvenue sur le live ! Oh mon Dieu, c'est quoi "
                  "ce bordel ? Mais non, frère. Mdr, c'est dingue !",
        "sample": "Oh mon Dieu, c'était quoi ça ! C'est une blague ?",
    },
    "it": {
        "reaction": {"incredibile", "assurdo", "aiuto", "morto", "morta", "pazzesco",
                     "madonna", "mamma", "ahahah", "noo", "follia"},
        "weak": {"no", "aspetta", "corri", "dai", "vieni", "fratello", "raga", "ragazzi",
                 "oh", "boh", "guarda"},
        "phrases": ["oddio", "mamma mia", "ma che", "non ci credo", "cos'era",
                    "stai scherzando", "sto morendo", "che succede", "non è possibile"],
        "swear_exact": {"cazzo", "merda", "stronzo", "stronza", "puttana", "minchia",
                        "coglione", "vaffanculo", "porco", "troia", "figa"},
        "swear_prefix": ("cazz", "incazz", "fanculo", "stronz", "porcodi"),
        "titles": {
            "laugh": ["Non riuscivo a smettere di ridere 😂", "Questa risata è contagiosa 😂",
                      "Sto piangendo dal ridere 😂"],
            "scream": ["Mi si è fermato il cuore 😱", "Mai urlato così 😱",
                       "Non me l'aspettavo 😱"],
            "chat": ["La chat è impazzita 😂", "La chat aveva ragione 💀",
                     "La chat l'aveva detto 😂"],
            "loud": ["Non l'ho vista arrivare 😳", "È successo tutto in un attimo 😳",
                     "Cos'è appena successo 💀"],
            "any": ["Aspetta la fine… 💀", "Miglior momento della live 🔥",
                    "Momento leggendario 🔥"],
            "game": ["È successo su {game} {e}", "{game} mi ha tradito {e}",
                     "Solo su {game} {e}"],
        },
        "hashtags": ["#divertente", "#gaming", "#fyp", "#viral", "#streamer", "#perte",
                     "#clips"],
        "laugh_tag": "#risate",
        "post_heads": ("IDEE PER IL TITOLO", "HASHTAG", "COPIA E INCOLLA"),
        "prompt": "Ciao ragazzi, benvenuti in live! Oddio, ma che cazzo? "
                  "Non ci credo, fratello. Ahahah, pazzesco!",
        "sample": "Oddio, cos'era quello! È uno scherzo?",
    },
    "pl": {
        "reaction": {"jezu", "boże", "masakra", "pomocy", "niemożliwe", "nieźle", "xd",
                     "kurde", "szok", "umieram", "nieee"},
        "weak": {"nie", "czekaj", "biegnij", "chodź", "dawaj", "stary", "ziomek", "ej",
                 "o", "no"},
        "phrases": ["o boże", "co to było", "nie no", "żartujesz", "co się dzieje",
                    "nie wierzę", "nie mogę", "co jest"],
        "swear_exact": {"kurwa", "chuj", "huj", "pierdolę", "pierdole", "jebać", "jebac",
                        "suka", "dupa", "cholera", "spierdalaj", "pizda"},
        "swear_prefix": ("kurw", "pierdol", "jeban", "jebi", "spierdal", "chuj", "zajeb"),
        "titles": {
            "laugh": ["Nie mogłem przestać się śmiać 😂", "Ten śmiech jest zaraźliwy 😂",
                      "Płaczę ze śmiechu 😂"],
            "scream": ["Serce mi stanęło 😱", "Nigdy tak nie krzyczałem 😱",
                       "Tego się nie spodziewałem 😱"],
            "chat": ["Czat oszalał 😂", "Czat miał rację 💀", "Czat to przewidział 😂"],
            "loud": ["Nie spodziewałem się tego 😳", "Wszystko stało się tak szybko 😳",
                     "Co się właśnie stało 💀"],
            "any": ["Czekaj na koniec… 💀", "Najlepszy moment streama 🔥",
                    "Legendarny moment 🔥"],
            "game": ["To stało się w {game} {e}", "{game} mnie załatwił {e}",
                     "Tylko w {game} {e}"],
        },
        "hashtags": ["#śmieszne", "#gaming", "#fyp", "#viral", "#streamer", "#dlaciebie",
                     "#clips"],
        "laugh_tag": "#xd",
        "post_heads": ("POMYSŁY NA TYTUŁ", "HASHTAGI", "KOPIUJ-WKLEJ"),
        "prompt": "Siema, witajcie na streamie! O Boże, co to kurwa było? "
                  "Nie no, stary. Hahaha, masakra!",
        "sample": "O Boże, co to było! To jakiś żart?",
    },
    "ru": {
        "reaction": {"капец", "жесть", "кошмар", "ору", "помогите", "невероятно", "офигеть",
                     "обалдеть", "ахаха", "нееет", "умираю", "треш", "имба"},
        "weak": {"нет", "стой", "беги", "давай", "братан", "чел", "ребят", "о", "ой",
                 "блин", "смотри"},
        "phrases": ["о боже", "что это было", "да ладно", "ты серьёзно", "не может быть",
                    "что происходит", "я не могу", "я умираю"],
        "swear_exact": {"блять", "бля", "блядь", "сука", "хуй", "пиздец", "нахуй",
                        "похуй", "ебать", "ёб", "мудак", "пидор", "говно", "хрен"},
        "swear_prefix": ("бляд", "пизд", "хуй", "хуе", "хуё", "еба", "ебл", "ёба",
                         "заеб", "уеб", "наху", "сук"),
        "titles": {
            "laugh": ["Не мог перестать смеяться 😂", "Этот смех заразный 😂",
                      "Я плачу от смеха 😂"],
            "scream": ["У меня сердце остановилось 😱", "Никогда так не орал 😱",
                       "Такого я не ожидал 😱"],
            "chat": ["Чат взорвался 😂", "Чат был прав 💀", "Чат предупреждал 😂"],
            "loud": ["Такого никто не ожидал 😳", "Всё случилось так быстро 😳",
                     "Что сейчас произошло 💀"],
            "any": ["Досмотри до конца… 💀", "Лучший момент стрима 🔥",
                    "Легендарный момент 🔥"],
            "game": ["Это случилось в {game} {e}", "{game} меня подставил {e}",
                     "Только в {game} {e}"],
        },
        "hashtags": ["#смешно", "#gaming", "#fyp", "#viral", "#стример", "#рек",
                     "#clips"],
        "laugh_tag": "#ору",
        "post_heads": ("ИДЕИ ДЛЯ НАЗВАНИЯ", "ХЭШТЕГИ", "СКОПИРОВАТЬ"),
        "prompt": "Всем привет, добро пожаловать на стрим! О боже, что это было, блять? "
                  "Да ладно, братан. Ахаха, жесть!",
        "sample": "О боже, что это было! Это шутка?",
    },
    "ar": {
        "reaction": {"مستحيل", "والله", "صدمة", "يخرب", "انصدمت", "مت"},
        "weak": {"يا", "لا", "استنى", "تعال", "يلا", "شوف", "خلاص"},
        "phrases": ["يا الله", "ايش هذا", "شو هذا", "مستحيل", "والله العظيم",
                    "يا ساتر", "ما صدقت"],
        "swear_exact": {"كس", "زب", "شرموطة", "منيك", "خرا", "قحبة", "حمار", "كلب"},
        "swear_prefix": ("كسم", "شرموط", "منيو", "قحب"),
        "titles": {
            "laugh": ["ما قدرت أوقف ضحك 😂", "الضحكة هذي معدية 😂", "مت من الضحك 😂"],
            "scream": ["قلبي وقف 😱", "عمري ما صرخت كذا 😱", "ما توقعتها أبداً 😱"],
            "chat": ["الشات انفجر 😂", "الشات كان معه حق 💀", "الشات قالها 😂"],
            "loud": ["ما توقعت هذا أبداً 😳", "صار كل شيء بسرعة 😳", "ايش صار؟ 💀"],
            "any": ["انتظر النهاية… 💀", "أفضل لحظة في البث 🔥", "لحظة أسطورية 🔥"],
            "game": ["هذا صار في {game} {e}", "{game} غدر فيني {e}", "بس في {game} {e}"],
        },
        "hashtags": ["#ضحك", "#gaming", "#fyp", "#viral", "#ستريمر", "#اكسبلور",
                     "#clips"],
        "laugh_tag": "#هههه",
        "post_heads": ("أفكار للعنوان", "هاشتاقات", "انسخ والصق"),
        "prompt": "هلا والله يا شباب، أهلاً في البث! يا الله، ايش هذا؟ مستحيل يا رجال. هههههه!",
        "sample": "يا الله، ايش هذا! تمزح؟",
    },
}

# laughs written out in any language (matched on a lower-cased word)
LAUGH_WORDS = (
    r"(?:a?h[aeıiu]){2,}h?|(?:[kj][dsş]){2,}[kdjsş]*|(?:s[jk]){2,}\w*|x+d+|lo+l|"
    r"lmao|lmfao|asdf\w*|[ae]h[ae]h\w*|kah+kah\w*|ksksks\w*|"
    r"(?:ja){2,}j?|(?:je){2,}j?|(?:ji){2,}j?|k{4,}|(?:rs){2,}|mdr+|ptdr+|"
    r"(?:ха){2,}х?|(?:ах){2,}а?|(?:хе){2,}|ه{3,}|(?:哈){2,}|ㅋ{2,}|ㅎ{2,}|w{3,}|笑|草|"
    r"5{3,}|(?:хи){2,}"
)


def get(language: str | None) -> dict:
    """Data for a language (English for unknown ones)."""
    return DATA.get((language or "en").lower()[:2], DATA["en"])


def swear_sets(language: str | None = None) -> tuple[set, tuple]:
    """Swear words to censor. Known language: that language + English (people
    swear in English everywhere). Unknown/auto: all lists, but only words that
    can't be normal words elsewhere (Turkish 'am' is English 'am')."""
    code = (language or "").lower()[:2]
    if code in DATA:
        langs = {code, "en"}
    else:
        langs = set(DATA)
    exact: set = set()
    prefix: tuple = ()
    for c in langs:
        exact |= DATA[c]["swear_exact"]
        prefix += DATA[c]["swear_prefix"]
    if code not in DATA:
        exact -= {"am", "con", "ass", "damn", "porco", "suka"}
    return exact, prefix
