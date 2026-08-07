"""
JanSetu Assistant — knowledge base & mock chat engine.

Used automatically whenever the Gemini API key is missing or a Gemini call
fails, so the assistant stays fully functional offline. Answers are written in
plain, citizen-friendly language and translated into all five JanSetu
interface languages (English, हिंदी, मराठी, ಕನ್ನಡ, বাংলা).

The assistant NEVER fabricates system data: complaint statuses are looked up
live from the database (see `status_found_reply`), and every other question is
answered from the static knowledge base below.
"""

import re

# All supported interface languages (kept in sync with static/js/i18n.js).
LANGUAGES = ("en", "hi", "mr", "kn", "bn")

# Human-friendly complaint status labels, translated.
STATUS_LABELS = {
    "PENDING_VALIDATION": {
        "en": "Pending Validation", "hi": "सत्यापन लंबित", "mr": "पडताळणी प्रलंबित",
        "kn": "ಪರಿಶೀಲನೆ ಬಾಕಿ", "bn": "যাচাইকরণ বাকি",
    },
    "VERIFIED": {
        "en": "Verified", "hi": "सत्यापित", "mr": "सत्यापित",
        "kn": "ಪರಿಶೀಲಿಸಲಾಗಿದೆ", "bn": "যাচাইকৃত",
    },
    "REJECTED": {
        "en": "Rejected", "hi": "अस्वीकृत", "mr": "फेटाळले",
        "kn": "ತಿರಸ್ಕರಿಸಲಾಗಿದೆ", "bn": "বাতিল করা হয়েছে",
    },
    "RESOLVED": {
        "en": "Resolved", "hi": "हल हो गई", "mr": "सोडवले",
        "kn": "ಪರಿಹರಿಸಲಾಗಿದೆ", "bn": "সমাধান হয়েছে",
    },
}

def _norm(text: str) -> str:
    """Normalise text for keyword matching (lowercase, digits kept)."""
    return re.sub(r"[^a-z0-9\u0900-\u0DFF]+", " ", (text or "").lower())


# ---------------------------------------------------------------------------
# Knowledge base — each topic carries one answer per language.
# ---------------------------------------------------------------------------
# Keys mirror the questions citizens actually ask the assistant.
KB = {
    "submit": {
        "en": ("You can file a complaint from your Citizen Dashboard. Log in (or "
               "register as a citizen), open the “New Complaint” section, choose a "
               "category and describe the issue. You can also record audio, attach a "
               "photo and auto-detect your GPS location. Tap “Submit Complaint” and AI "
               "processes it instantly — you get a Complaint ID, a 6-digit PIN and a "
               "SHA-256 hash."),
        "hi": ("आप अपने नागरिक डैशबोर्ड से शिकायत दर्ज कर सकते हैं। लॉगिन करें (या नागरिक "
               "के रूप में पंजीकरण करें), 'नई शिकायत' खोलें, श्रेणी चुनें और समस्या लिखें। "
               "साथ ही ऑडियो रिकॉर्ड कर सकते हैं, फोटो लगा सकते हैं और अपनी GPS लोकेशन स्वतः "
               "पता कर सकते हैं। 'शिकायत जमा करें' दबाएँ — AI इसे तुरंत प्रोसेस करता है और "
               "आपको शिकायत आईडी, 6-अंकीय PIN और SHA-256 हैश मिलता है।"),
        "mr": ("तुम्ही तुमच्या नागरिक डॅशबोर्डवरून तक्रार नोंदवू शकता. लॉगिन करा (किंवा नागरिक "
               "म्हणून नोंदणी करा), 'नवीन तक्रार' उघडा, श्रेणी निवडा आणि समस्या लिहा. ऑडिओ "
               "रेकॉर्ड, फोटो आणि GPS लोकेशनही जोडता येते. 'तक्रार सादर करा' दाबा — AI ती "
               "लगेच प्रक्रिया करते आणि तुम्हाला तक्रार आयडी, 6-अंकी PIN आणि SHA-256 हैश मिळतो."),
        "kn": ("ನಿಮ್ಮ ನಾಗರಿಕ ಡ್ಯಾಶ್ಬೋರ್ಡ್‌ನಿಂದ ದೂರು ಸಲ್ಲಿಸಬಹುದು. ಲಾಗಿನ್ ಮಾಡಿ (ಅಥವಾ ನಾಗರಿಕರಾಗಿ "
               "ನೋಂದಾಯಿಸಿ), 'ಹೊಸ ದೂರು' ವಿಭಾಗ ತೆರೆಯಿರಿ, ವರ್ಗ ಆಯ್ಕೆಮಾಡಿ ಮತ್ತು ಸಮಸ್ಯೆಯನ್ನು ವಿವರಿಸಿ. "
               "ಧ್ವನಿ ರೆಕಾರ್ಡ್, ಫೋಟೋ ಮತ್ತು ನಿಮ್ಮ GPS ಸ್ಥಳವನ್ನೂ ಸೇರಿಸಬಹುದು. 'ದೂರು ಸಲ್ಲಿಸಿ' ಒತ್ತಿರಿ — "
               "AI ಅದನ್ನು ತಕ್ಷಣ ಪ್ರಕ್ರಿಯೆ ಮಾಡಿ ನಿಮಗೆ ದೂರು ID, 6-ಅಂಕಿಯ PIN ಮತ್ತು SHA-256 ಹ್ಯಾಶ್ ನೀಡುತ್ತದೆ."),
        "bn": ("আপনি আপনার নাগরিক ড্যাশবোর্ড থেকে অভিযোগ দাখিল করতে পারেন। লগইন করুন (বা নাগরিক "
               "হিসেবে নিবন্ধন করুন), 'নতুন অভিযোগ' বিভাগ খুলুন, ক্যাটাগরি বেছে নিন এবং সমস্যাটি "
               "লিখুন। অডিও রেকর্ড, ছবি এবং আপনার GPS অবস্থানও যোগ করতে পারেন। 'অভিযোগ জমা দিন' "
               "চাপুন — AI এটি সাথে সাথে প্রক্রিয়া করে এবং আপনি অভিযোগ ID, ৬-অঙ্কের PIN ও "
               "SHA-256 হ্যাশ পান।"),
    },
    "track": {
        "en": ("To track a complaint, tap “Track This Complaint” right after submission, "
               "or open your Dashboard → My Complaints to see every status. You can also "
               "ask me here: share your Complaint ID (it looks like JST-4K9XM2P7) and I "
               "will look up its live status for you."),
        "hi": ("शिकायत ट्रैक करने के लिए जमा करने के तुरंत बाद 'शिकायत ट्रैक करें' दबाएँ, या "
               "अपने डैशबोर्ड → मेरी शिकायतें में जाएँ। आप यहाँ अपनी शिकायत आईडी (जैसे "
               "JST-4K9XM2P7) बताकर भी मुझसे लाइव स्थिति पूछ सकते हैं।"),
        "mr": ("तक्रार ट्रॅक करण्यासाठी सादर केल्यावर लगेच 'तक्रार ट्रॅक करा' दाबा, किंवा "
               "डॅशबोर्ड → माझ्या तक्रारी उघडा. तुम्ही तक्रार आयडी (जसे JST-4K9XM2P7) देऊन "
               "मलाही लाइव स्थिती विचारू शकता."),
        "kn": ("ದೂರನ್ನು ಟ್ರ್ಯಾಕ್ ಮಾಡಲು ಸಲ್ಲಿಸಿದ ತಕ್ಷಣ 'ದೂರು ಟ್ರ್ಯಾಕ್ ಮಾಡಿ' ಒತ್ತಿರಿ, ಅಥವಾ "
               "ಡ್ಯಾಶ್ಬೋರ್ಡ್ → ನನ್ನ ದೂರುಗಳು ತೆರೆಯಿರಿ. ನಿಮ್ಮ ದೂರು ID (JST-4K9XM2P7 ರೀತಿ) "
               "ಹೇಳಿದರೆ ನಾನು ಅದರ ಲೈವ್ ಸ್ಥಿತಿಯನ್ನು ಪರಿಶೀಲಿಸಬಲ್ಲೆ."),
        "bn": ("অভিযোগ ট্র্যাক করতে জমা দেওয়ার পরপরই 'অভিযোগ ট্র্যাক করুন' চাপুন, অথবা ড্যাশবোর্ড → "
               "আমার অভিযোগ খুলুন। আপনি এখানে আপনার অভিযোগ ID (যেমন JST-4K9XM2P7) জানালে আমি "
               "তার লাইভ অবস্থা দেখে দিতে পারি।"),
    },
    "complaint_id": {
        "en": ("Every complaint gets a unique ID like JST-4K9XM2P7. It is your reference "
               "number for tracking and for officials to find your complaint quickly. "
               "Keep it safe — you will need it to check status."),
        "hi": ("हर शिकायत को JST-4K9XM2P7 जैसी अनोखी आईडी मिलती है। यह ट्रैकिंग के लिए आपका "
               "संदर्भ नंबर है और इससे अधिकारी आपकी शिकायत जल्दी ढूँढ सकते हैं। इसे सुरक्षित रखें।"),
        "mr": ("प्रत्येक तक्रारीला JST-4K9XM2P7 सारखी अनोखी आयडी मिळते. ही ट्रॅकिंगसाठी तुमची "
               "संदर्भ संख्या आहे. ती सुरक्षित ठेवा."),
        "kn": ("ಪ್ರತಿ ದೂರಿಗೆ JST-4K9XM2P7 ರೀತಿಯ ಅನನ್ಯ ID ಸಿಗುತ್ತದೆ. ಅದು ಟ್ರ್ಯಾಕಿಂಗ್‌ಗೆ ನಿಮ್ಮ "
               "ಉಲ್ಲೇಖ ಸಂಖ್ಯೆ. ಅದನ್ನು ಸುರಕ್ಷಿತವಾಗಿಡಿ."),
        "bn": ("প্রতিটি অভিযোগের জন্য JST-4K9XM2P7-এর মতো একটি অনন্য ID থাকে। এটি ট্র্যাকিংয়ের "
               "জন্য আপনার রেফারেন্স নম্বর। এটি নিরাপদে রাখুন।"),
    },
    "pin": {
        "en": ("Your 6-digit PIN is a private key linked to your complaint. It is shown "
               "only to you, the complaint owner, and is used to prove ownership. Never "
               "share it with anyone."),
        "hi": ("आपका 6-अंकीय PIN आपकी शिकायत से जुड़ी निजी चाबी है। यह केवल आपको दिखाई देता "
               "है और इससे स्वामित्व सिद्ध होता है। इसे कभी किसी के साथ साझा न करें।"),
        "mr": ("तुमचा 6-अंकी PIN ही तक्रारीशी जोडलेली खाजगी किल्ली आहे. ती फक्त तुम्हालाच "
               "दिसते. ती कोणाशीही शेअर करू नका."),
        "kn": ("ನಿಮ್ಮ 6-ಅಂಕಿಯ PIN ನಿಮ್ಮ ದೂರಿಗೆ ಸಂಬಂಧಿಸಿದ ಖಾಸಗಿ ಕೀಲಿ. ಅದು ನಿಮಗೆ ಮಾತ್ರ "
               "ಗೋಚರಿಸುತ್ತದೆ. ಅದನ್ನು ಯಾರೊಂದಿಗೂ ಹಂಚಿಕೊಳ್ಳಬೇಡಿ."),
        "bn": ("আপনার ৬-অঙ্কের PIN আপনার অভিযোগের সাথে যুক্ত একটি ব্যক্তিগত চাবি। এটি শুধুমাত্র "
               "আপনাকে দেখানো হয়। এটি কখনও কারও সাথে ভাগ করবেন না।"),
    },
    "photo": {
        "en": ("You can capture a photo with your camera or upload one from the "
               "dashboard's 'Capture Photo' tile before submitting. Clear photos of the "
               "issue help validators confirm your complaint faster."),
        "hi": ("जमा करने से पहले आप कैमरे से फोटो ले सकते हैं या 'फोटो लें' टाइल से अपलोड कर "
               "सकते हैं। समस्या की साफ तस्वीरें सत्यापनकर्ता को आपकी शिकायत की जल्दी पुष्टि "
               "करने में मदद करती हैं।"),
        "mr": ("सादर करण्यापूर्वी तुम्ही कॅमेऱ्याने फोटो घेऊ शकता किंवा 'फोटो घ्या' वरून "
               "अपलोड करू शकता. स्पष्ट फोटो पडताळणीत मदत करतात."),
        "kn": ("ಸಲ್ಲಿಸುವ ಮೊದಲು ನಿಮ್ಮ ಕ್ಯಾಮೆರಾದಿಂದ ಫೋಟೋ ತೆಗೆಯಬಹುದು ಅಥವಾ 'ಫೋಟೋ ತೆಗೆಯಿರಿ' "
               "ಟೈಲ್‌ನಿಂದ ಅಪ್‌ಲೋಡ್ ಮಾಡಬಹುದು. ಸ್ಪಷ್ಟ ಫೋಟೋಗಳು ಪರಿಶೀಲನೆಯನ್ನು ವೇಗಗೊಳಿಸುತ್ತವೆ."),
        "bn": ("জমা দেওয়ার আগে আপনি ক্যামেরা দিয়ে ছবি তুলতে পারেন বা 'ছবি তুলুন' থেকে আপলোড "
               "করতে পারেন। সমস্যার পরিষ্কার ছবি যাচাই প্রক্রিয়া দ্রুত করে।"),
    },
    "gps": {
        "en": ("JanSetu uses your browser's location to attach the exact GPS coordinates "
               "and street address to your complaint automatically. This helps the right "
               "department reach the exact spot. You can allow or deny it — and you can "
               "always type the location manually."),
        "hi": ("JanSetu आपके ब्राउज़र की लोकेशन का उपयोग करके सटीक GPS निर्देशांक और पता आपकी "
               "शिकायत से अपने आप जोड़ देता है। इससे सही विभाग सही जगह पहुँच पाता है। आप अनुमति "
               "दे या न दे सकते हैं — और पता मैन्युअल भी लिख सकते हैं।"),
        "mr": ("JanSetu ब्राउझर लोकेशन वापरून अचूक GPS निर्देशांक आणि पत्ता तक्रारीशी "
               "आपोआप जोडते. यामुळे योग्य विभाग अचूक ठिकाणी पोहोचतो. तुम्ही परवानगी देऊ शकता "
               "किंवा पत्ता स्वतःही लिहू शकता."),
        "kn": ("JanSetu ನಿಮ್ಮ ಬ್ರೌಸರ್‌ನ ಸ್ಥಳವನ್ನು ಬಳಸಿ ನಿಖರ GPS ನಿರ್ದೇಶಾಂಕಗಳು ಮತ್ತು ವಿಳಾಸವನ್ನು "
               "ದೂರಿಗೆ ಸ್ವಯಂಚಾಲಿತವಾಗಿ ಲಗತ್ತಿಸುತ್ತದೆ. ಇದರಿಂದ ಸರಿಯಾದ ಇಲಾಖೆ ನಿಖರ ಸ್ಥಳಕ್ಕೆ ತಲುಪುತ್ತದೆ. "
               "ನೀವು ಅನುಮತಿಸಬಹುದು ಅಥವಾ ವಿಳಾಸವನ್ನು ಹಸ್ತಚಾಲಿತವಾಗಿಯೂ ನಮೂದಿಸಬಹುದು."),
        "bn": ("JanSetu আপনার ব্রাউজারের অবস্থান ব্যবহার করে সঠিক GPS স্থানাঙ্ক এবং ঠিকানা "
               "স্বয়ংক্রিয়ভাবে অভিযোগের সাথে যুক্ত করে। এতে সঠিক বিভাগ সঠিক জায়গায় পৌঁছায়। আপনি "
               "অনুমতি দিতে বা না দিতে পারেন — ঠিকানা হাতে লিখেও দিতে পারেন।"),
    },
    "after_submit": {
        "en": ("After you submit, AI transcribes any audio, removes personal information, "
               "writes a summary and scores urgency (1–10). The complaint moves to "
               "'Pending Validation'. A validator reviews the evidence and either verifies "
               "or rejects it, then the official department handles it until it is "
               "resolved. You can follow every step in the complaint timeline."),
        "hi": ("जमा करने के बाद AI ऑडियो ट्रांसक्राइब करता है, निजी जानकारी हटाता है, सारांश "
               "लिखता है और तात्कालिकता (1–10) स्कोर देता है। शिकायत 'सत्यापन लंबित' में जाती है। "
               "सत्यापनकर्ता साक्ष्य जाँचता है और फिर अधिकारी विभाग समाधान तक कार्रवाई करता है।"),
        "mr": ("सादर केल्यावर AI ऑडिओ लिहिते, खाजगी माहिती काढते, सारांश बनवते आणि तातडीचेपणा "
               "(1–10) स्कोर देते. तक्रार 'पडताळणी प्रलंबित' मध्ये जाते. पडताळणीकर्ता पुरावा "
               "तपासतो आणि मग अधिकारी विभाग निराकरणापर्यंत कारवाई करतो."),
        "kn": ("ಸಲ್ಲಿಸಿದ ನಂತರ AI ಆಡಿಯೋ ಲಿಪ್ಯಂತರ ಮಾಡುತ್ತದೆ, ವೈಯಕ್ತಿಕ ಮಾಹಿತಿ ತೆಗೆದು, ಸಾರಾಂಶ "
               "ಬರೆದು ತುರ್ತು (1–10) ಸ್ಕೋರ್ ನೀಡುತ್ತದೆ. ದೂರು 'ಪರಿಶೀಲನೆ ಬಾಕಿ' ಗೆ ಹೋಗುತ್ತದೆ. "
               "ಪರಿಶೀಲಕ ಸಾಕ್ಷ್ಯವನ್ನು ಪರಿಶೀಲಿಸಿ, ನಂತರ ಅಧಿಕಾರಿ ಇಲಾಖೆ ಪರಿಹಾರದವರೆಗೆ ಕಾರ್ಯನಿರ್ವಹಿಸುತ್ತದೆ."),
        "bn": ("জমা দেওয়ার পর AI অডিও লিপিবদ্ধ করে, ব্যক্তিগত তথ্য মুছে দেয়, সারাংশ লেখে এবং "
               "জরুরিতা (১–১০) স্কোর দেয়। অভিযোগ 'যাচাইকরণ বাকি'-তে যায়। যাচাইকারী প্রমাণ "
               "পরীক্ষা করে, তারপর সংশ্লিষ্ট বিভাগ সমাধান না হওয়া পর্যন্ত কাজ করে।"),
    },
    "pending": {
        "en": ("'Pending Validation' means your complaint has been submitted and is "
               "waiting for a validator to review the evidence (audio, photo, location) "
               "before it moves to the official department."),
        "hi": ("'सत्यापन लंबित' का अर्थ है आपकी शिकायत जमा हो गई है और सत्यापनकर्ता साक्ष्य की "
               "जाँच कर रहा है, उसके बाद ही यह अधिकारी विभाग तक पहुँचेगी।"),
        "mr": ("'पडताळणी प्रलंबित' म्हणजे तुमची तक्रार सादर झाली आहे आणि पडताळणीकर्ता पुरावा "
               "तपासत आहे. त्यानंतर ती अधिकारी विभागाकडे जाईल."),
        "kn": ("'ಪರಿಶೀಲನೆ ಬಾಕಿ' ಎಂದರೆ ನಿಮ್ಮ ದೂರು ಸಲ್ಲಿಸಲಾಗಿದ್ದು, ಪರಿಶೀಲಕ ಸಾಕ್ಷ್ಯವನ್ನು ಪರಿಶೀಲಿಸುತ್ತಿದ್ದಾರೆ. "
               "ನಂತರ ಅದು ಅಧಿಕಾರಿ ಇಲಾಖೆಗೆ ಹೋಗುತ್ತದೆ."),
        "bn": ("'যাচাইকরণ বাকি' মানে আপনার অভিযোগ জমা হয়েছে এবং যাচাইকারী প্রমাণ পরীক্ষা করছেন। "
               "তারপর এটি সংশ্লিষ্ট বিভাগে যায়।"),
    },
    "verified": {
        "en": ("'Verified' means a validator has reviewed your complaint and confirmed it "
               "is genuine. It now goes to the official department for action."),
        "hi": ("'सत्यापित' का अर्थ है सत्यापनकर्ता ने आपकी शिकायत की जाँच कर पुष्टि कर दी है। "
               "अब यह कार्रवाई के लिए अधिकारी विभाग के पास जाती है।"),
        "mr": ("'सत्यापित' म्हणजे पडताळणीकर्त्याने तुमची तक्रार तपासून खरी असल्याची पुष्टी केली "
               "आहे. आता ती कारवाईसाठी विभागाकडे जाते."),
        "kn": ("'ಪರಿಶೀಲಿಸಲಾಗಿದೆ' ಎಂದರೆ ಪರಿಶೀಲಕ ನಿಮ್ಮ ದೂರನ್ನು ಪರಿಶೀಲಿಸಿ ಅದು ನಿಜವೆಂದು ದೃಢಪಡಿಸಿದ್ದಾರೆ. "
               "ಈಗ ಅದು ಕ್ರಮಕ್ಕಾಗಿ ಅಧಿಕಾರಿ ಇಲಾಖೆಗೆ ಹೋಗುತ್ತದೆ."),
        "bn": ("'যাচাইকৃত' মানে যাচাইকারী আপনার অভিযোগ পরীক্ষা করে সেটি সঠিক বলে নিশ্চিত করেছেন। "
               "এখন এটি পদক্ষেপের জন্য সংশ্লিষ্ট বিভাগে যায়।"),
    },
    "resolved": {
        "en": ("'Resolved' means the official department has acted on your complaint and "
               "marked it as resolved. You can read the official's remarks in the "
               "complaint details."),
        "hi": ("'हल हो गई' का अर्थ है अधिकारी विभाग ने आपकी शिकायत पर कार्रवाई कर ली है। आप "
               "शिकायत विवरण में अधिकारी की टिप्पणियाँ पढ़ सकते हैं।"),
        "mr": ("'सोडवले' म्हणजे अधिकारी विभागाने तुमच्या तक्रारीवर कारवाई केली आहे. तक्रार "
               "तपशीलात अधिकाऱ्याचे शेरे वाचता येतात."),
        "kn": ("'ಪರಿಹರಿಸಲಾಗಿದೆ' ಎಂದರೆ ಅಧಿಕಾರಿ ಇಲಾಖೆ ನಿಮ್ಮ ದೂರಿನ ಮೇಲೆ ಕ್ರಮ ತೆಗೆದುಕೊಂಡಿದೆ. "
               "ದೂರಿನ ವಿವರದಲ್ಲಿ ಅಧಿಕಾರಿಯ ಟಿಪ್ಪಣಿ ಓದಬಹುದು."),
        "bn": ("'সমাধান হয়েছে' মানে সংশ্লিষ্ট বিভাগ আপনার অভিযোগের উপর ব্যবস্থা নিয়েছে। অভিযোগের "
               "বিস্তারিতে কর্মকর্তার মন্তব্য পড়তে পারবেন।"),
    },
    "rejected": {
        "en": ("If your complaint is rejected, it means the validator could not confirm "
               "it. You will see the reason in the remarks. You can submit a new "
               "complaint with clearer evidence, better photos or a more accurate "
               "location."),
        "hi": ("अगर शिकायत अस्वीकृत हो जाए तो सत्यापनकर्ता उसकी पुष्टि नहीं कर सका। टिप्पणियों "
               "में कारण देखें। बेहतर साक्ष्य, साफ फोटो या सटीक लोकेशन के साथ नई शिकायत दर्ज करें।"),
        "mr": ("तक्रार फेटाळली गेली तर पडताळणीकर्त्याला तिची पुष्टी होऊ शकली नाही. शेऱ्यांमध्ये "
               "कारण दिसेल. स्पष्ट पुराव्यासह नवीन तक्रार नोंदवा."),
        "kn": ("ದೂರನ್ನು ತಿರಸ್ಕರಿಸಿದರೆ ಪರಿಶೀಲಕ ಅದನ್ನು ದೃಢೀಕರಿಸಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ ಎಂದರ್ಥ. ಟಿಪ್ಪಣಿಯಲ್ಲಿ "
               "ಕಾರಣ ಕಾಣುತ್ತದೆ. ಸ್ಪಷ್ಟ ಸಾಕ್ಷ್ಯದೊಂದಿಗೆ ಹೊಸ ದೂರು ಸಲ್ಲಿಸಿ."),
        "bn": ("যদি অভিযোগ বাতিল হয়, তার মানে যাচাইকারী এটি নিশ্চিত করতে পারেননি। মন্তব্যে কারণ "
               "পাবেন। স্পষ্ট প্রমাণসহ নতুন অভিযোগ জমা দিন।"),
    },
    "time": {
        "en": ("Most complaints are reviewed by a validator within a few working days. "
               "Resolution time depends on the department and the nature of the issue — "
               "complaints with a high urgency score are prioritised."),
        "hi": ("अधिकांश शिकायतें कुछ कार्यदिवसों में सत्यापित हो जाती हैं। समाधान का समय विभाग "
               "और समस्या पर निर्भर करता है — उच्च तात्कालिकता वाली शिकायतों को प्राथमिकता दी जाती है।"),
        "mr": ("बहुतेक तक्रारी काही कामकाजी दिवसांत पडताळल्या जातात. निराकरणाची वेळ विभाग आणि "
               "समस्येवर अवलंबून असते — उच्च तातडीचेपणा असलेल्या तक्रारींना प्राधान्य दिले जाते."),
        "kn": ("ಹೆಚ್ಚಿನ ದೂರುಗಳು ಕೆಲವು ಕೆಲಸದ ದಿನಗಳಲ್ಲಿ ಪರಿಶೀಲಿಸಲ್ಪಡುತ್ತವೆ. ಪರಿಹಾರದ ಸಮಯ ಇಲಾಖೆ "
               "ಮತ್ತು ಸಮಸ್ಯೆಯನ್ನು ಅವಲಂಬಿಸಿರುತ್ತದೆ — ಹೆಚ್ಚಿನ ತುರ್ತು ಸ್ಕೋರ್ ಇರುವ ದೂರುಗಳಿಗೆ ಆದ್ಯತೆ ಸಿಗುತ್ತದೆ."),
        "bn": ("বেশিরভাগ অভিযোগ কয়েক কর্মদিবসের মধ্যে যাচাই হয়। সমাধানের সময় বিভাগ ও সমস্যার "
               "ধরনের উপর নির্ভর করে — উচ্চ জরুরিতা স্কোরের অভিযোগে অগ্রাধিকার দেওয়া হয়।"),
    },
    "department": {
        "en": ("Your complaint is routed by its category — Roads & Transport, Water "
               "Supply, Electricity and so on — and the right department is picked "
               "during validation. For direct contact details of a specific department, "
               "please check your state's official grievance portal or helpline."),
        "hi": ("आपकी शिकायत श्रेणी के अनुसार भेजी जाती है — सड़क और परिवहन, जल आपूर्ति, बिजली "
               "आदि — और सत्यापन के दौरान सही विभाग चुना जाता है। किसी विशेष विभाग के संपर्क "
               "विवरण के लिए अपने राज्य के आधिकारिक पोर्टल या हेल्पलाइन देखें।"),
        "mr": ("तुमची तक्रार श्रेणीनुसार पाठवली जाते — रस्ते आणि वाहतूक, पाणीपुरवठा, वीज इ. — आणि "
               "पडताळणीदरम्यान योग्य विभाग निवडला जातो. विशिष्ट विभागाच्या संपर्कासाठी राज्याच्या "
               "अधिकृत पोर्टल किंवा हेल्पलाइन पहा."),
        "kn": ("ನಿಮ್ಮ ದೂರನ್ನು ವರ್ಗದ ಪ್ರಕಾರ ರವಾನಿಸಲಾಗುತ್ತದೆ — ರಸ್ತೆ ಮತ್ತು ಸಾರಿಗೆ, ನೀರು ಸರಬರಾಜು, "
               "ವಿದ್ಯುತ್ ಇತ್ಯಾದಿ — ಮತ್ತು ಪರಿಶೀಲನೆಯ ಸಮಯದಲ್ಲಿ ಸರಿಯಾದ ಇಲಾಖೆಯನ್ನು ಆಯ್ಕೆ ಮಾಡಲಾಗುತ್ತದೆ. "
               "ನಿರ್ದಿಷ್ಟ ಇಲಾಖೆಯ ಸಂಪರ್ಕ ವಿವರಗಳಿಗೆ ನಿಮ್ಮ ರಾಜ್ಯದ ಅಧಿಕೃತ ಪೋರ್ಟಲ್ ನೋಡಿ."),
        "bn": ("আপনার অভিযোগ ক্যাটাগরি অনুযায়ী রুট হয় — রাস্তা ও পরিবহন, পানি সরবরাহ, বিদ্যুৎ ইত্যাদি — "
               "এবং যাচাইয়ের সময় সঠিক বিভাগ বাছাই করা হয়। নির্দিষ্ট বিভাগের যোগাযোগের জন্য আপনার "
               "রাজ্যের সরকারি পোর্টাল দেখুন।"),
    },
    "edit": {
        "en": ("Complaints cannot be edited after submission to keep the record "
               "tamper-proof (each one carries a SHA-256 integrity hash). If you need to "
               "correct something, please submit a new complaint with the right details."),
        "hi": ("जालसाजी से बचाने के लिए (हर शिकायत पर SHA-256 हैश होता है) शिकायत जमा करने के बाद "
               "उसे संपादित नहीं किया जा सकता। कुछ सुधारना हो तो सही विवरण के साथ नई शिकायत दर्ज करें।"),
        "mr": ("तक्रार सादर केल्यानंतर ती संपादित करता येत नाही (प्रत्येक तक्रारीवर SHA-256 हैश "
               "असतो). काही सुधारायचे असल्यास योग्य माहितीसह नवीन तक्रार नोंदवा."),
        "kn": ("ದೂರು ಸಲ್ಲಿಸಿದ ನಂತರ ಅದನ್ನು ಸಂಪಾದಿಸಲು ಸಾಧ್ಯವಿಲ್ಲ (ಪ್ರತಿ ದೂರಿಗೆ SHA-256 ಹ್ಯಾಶ್ ಇರುತ್ತದೆ). "
               "ಏನಾದರೂ ಸರಿಪಡಿಸಬೇಕಾದರೆ ಸರಿಯಾದ ವಿವರಗಳೊಂದಿಗೆ ಹೊಸ ದೂರು ಸಲ್ಲಿಸಿ."),
        "bn": ("রেকর্ড নিরাপদ রাখতে (প্রতিটি অভিযোগে SHA-256 হ্যাশ থাকে) জমা দেওয়ার পর অভিযোগ "
               "সম্পাদনা করা যায় না। কিছু সংশোধন করতে চাইলে সঠিক তথ্যসহ নতুন অভিযোগ জমা দিন।"),
    },
    "history": {
        "en": ("All your submitted complaints appear under 'My Complaints' in your citizen "
               "dashboard, each with its latest status and a timeline you can open for "
               "full details."),
        "hi": ("आपकी सभी शिकायतें आपके नागरिक डैशबोर्ड के 'मेरी शिकायतें' में दिखती हैं, साथ ही "
               "उनकी स्थिति और समयरेखा भी देख सकते हैं।"),
        "mr": ("तुमच्या सर्व तक्रारी नागरिक डॅशबोर्डच्या 'माझ्या तक्रारी' मध्ये दिसतात. तिथे "
               "स्थिती आणि टाइमलाइनही पाहता येते."),
        "kn": ("ನಿಮ್ಮ ಎಲ್ಲಾ ದೂರುಗಳು ನಾಗರಿಕ ಡ್ಯಾಶ್ಬೋರ್ಡ್‌ನ 'ನನ್ನ ದೂರುಗಳು' ನಲ್ಲಿ ಕಾಣುತ್ತವೆ, "
               "ಸ್ಥಿತಿ ಮತ್ತು ಟೈಮ್‌ಲೈನ್‌ನೊಂದಿಗೆ."),
        "bn": ("আপনার সব অভিযোগ নাগরিক ড্যাশবোর্ডের 'আমার অভিযোগ'-এ দেখা যায়, অবস্থা ও টাইমলাইনসহ।"),
    },
    "urgency": {
        "en": ("The urgency score (1–10) is assigned by AI based on risk to safety and "
               "health and how many people are affected. Higher scores are prioritised "
               "by validators and departments."),
        "hi": ("तात्कालिकता स्कोर (1–10) AI सुरक्षा, स्वास्थ्य के जोखिम और प्रभावित लोगों की "
               "संख्या के आधार पर देता है। उच्च स्कोर वाली शिकायतों को प्राथमिकता दी जाती है।"),
        "mr": ("तातडीचेपणा स्कोर (1–10) AI सुरक्षा, आरोग्याच्या जोखमीवर आणि प्रभावित लोकांवर "
               "आधारित देतो. उच्च स्कोर असलेल्या तक्रारींना प्राधान्य मिळते."),
        "kn": ("ತುರ್ತು ಸ್ಕೋರ್ (1–10) ಅನ್ನು AI ಸುರಕ್ಷತೆ, ಆರೋಗ್ಯದ ಅಪಾಯ ಮತ್ತು ಪರಿಣಾಮಕ್ಕೊಳಗಾದ ಜನರ "
               "ಆಧಾರದ ಮೇಲೆ ನೀಡುತ್ತದೆ. ಹೆಚ್ಚಿನ ಸ್ಕೋರ್ ಇರುವ ದೂರುಗಳಿಗೆ ಆದ್ಯತೆ ಸಿಗುತ್ತದೆ."),
        "bn": ("জরুরিতা স্কোর (১–১০) AI নিরাপত্তা ও স্বাস্থ্যের ঝুঁকি এবং কতজন মানুষ প্রভাবিত তার "
               "ভিত্তিতে দেয়। উচ্চ স্কোরের অভিযোগে অগ্রাধিকার দেওয়া হয়।"),
    },
    "ai": {
        "en": ("AI transcribes your audio recording, removes personal details (names, "
               "phones, addresses) to protect your privacy, writes a short summary, "
               "confirms the right category and scores urgency. Your data is "
               "de-identified before it is stored."),
        "hi": ("AI आपके ऑडियो को ट्रांसक्राइब करता है, गोपनीयता के लिए निजी जानकारी (नाम, फोन, "
               "पता) हटाता है, संक्षिप्त सारांश लिखता है, सही श्रेणी की पुष्टि करता है और "
               "तात्कालिकता स्कोर देता है। आपका डेटा सुरक्षित रूप से संग्रहीत होता है।"),
        "mr": ("AI ऑडिओ लिहिते, गोपनीयतेसाठी खाजगी माहिती (नावे, फोन, पत्ते) काढते, थोडक्यात "
               "सारांश लिहिते, योग्य श्रेणीची पुष्टी करते आणि तातडीचेपणा स्कोर देते."),
        "kn": ("AI ನಿಮ್ಮ ಆಡಿಯೋ ಲಿಪ್ಯಂತರ ಮಾಡಿ, ಗೌಪ್ಯತೆಗಾಗಿ ವೈಯಕ್ತಿಕ ವಿವರಗಳನ್ನು (ಹೆಸರು, ಫೋನ್, "
               "ವಿಳಾಸ) ತೆಗೆದು, ಸಣ್ಣ ಸಾರಾಂಶ ಬರೆದು, ಸರಿಯಾದ ವರ್ಗ ದೃಢಪಡಿಸಿ ತುರ್ತು ಸ್ಕೋರ್ ನೀಡುತ್ತದೆ."),
        "bn": ("AI আপনার অডিও লিপিবদ্ধ করে, গোপনীয়তার জন্য ব্যক্তিগত তথ্য (নাম, ফোন, ঠিকানা) "
               "মুছে দেয়, সংক্ষিপ্ত সারাংশ লেখে, সঠিক ক্যাটাগরি নিশ্চিত করে এবং জরুরিতা স্কোর দেয়।"),
    },
    "location": {
        "en": ("Your location helps the right department reach the exact spot and lets "
               "validators confirm the complaint. It is captured only with your "
               "permission — you can also enter it manually."),
        "hi": ("आपकी लोकेशन से सही विभाग सही जगह पहुँच पाता है और सत्यापनकर्ता शिकायत की पुष्टि "
               "कर पाते हैं। यह केवल आपकी अनुमति से ली जाती है — आप इसे मैन्युअल भी भर सकते हैं।"),
        "mr": ("तुमच्या लोकेशनमुळे योग्य विभाग अचूक ठिकाणी पोहोचतो आणि पडताळणीकर्ता तक्रारीची "
               "पुष्टी करतो. ती फक्त तुमच्या परवानगीने घेतली जाते."),
        "kn": ("ನಿಮ್ಮ ಸ್ಥಳದಿಂದ ಸರಿಯಾದ ಇಲಾಖೆ ನಿಖರ ಸ್ಥಳಕ್ಕೆ ತಲುಪುತ್ತದೆ ಮತ್ತು ಪರಿಶೀಲಕರು ದೂರನ್ನು "
               "ದೃಢಪಡಿಸುತ್ತಾರೆ. ಅದನ್ನು ನಿಮ್ಮ ಅನುಮತಿಯಿಂದ ಮಾತ್ರ ಪಡೆಯಲಾಗುತ್ತದೆ."),
        "bn": ("আপনার অবস্থান সঠিক বিভাগকে সঠিক জায়গায় পৌঁছাতে সাহায্য করে এবং যাচাইকারী অভিযোগ "
               "নিশ্চিত করতে পারেন। এটি শুধুমাত্র আপনার অনুমতি নিয়ে নেওয়া হয়।"),
    },
    "language": {
        "en": ("Use the globe icon in the top bar to switch between English, हिंदी, "
               "मराठी, ಕನ್ನಡ and বাংলা. The whole interface changes instantly — and I "
               "will answer in your selected language too."),
        "hi": ("ऊपर की पट्टी में ग्लोब आइकन से English, हिंदी, मराठी, ಕನ್ನಡ और বাংলা के बीच बदलें। "
               "पूरा इंटरफ़ेस तुरंत बदल जाता है — और मैं भी आपकी चुनी हुई भाषा में जवाब दूँगा।"),
        "mr": ("वरच्या पट्टीतील ग्लोब आयकॉनवरून English, हिंदी, मराठी, ಕನ್ನಡ आणि বাংলা दरम्यान "
               "बदला. मीही तुमच्या निवडलेल्या भाषेत उत्तर देईन."),
        "kn": ("ಮೇಲಿನ ಪಟ್ಟಿಯಲ್ಲಿನ ಗ್ಲೋಬ್ ಐಕಾನ್ ಬಳಸಿ English, हिंदी, मराठी, ಕನ್ನಡ ಮತ್ತು বাংলা "
               "ನಡುವೆ ಬದಲಿಸಿ. ನಾನೂ ನಿಮ್ಮ ಆಯ್ಕೆಯ ಭಾಷೆಯಲ್ಲಿ ಉತ್ತರಿಸುತ್ತೇನೆ."),
        "bn": ("উপরের বারে গ্লোব আইকন ব্যবহার করে English, हिंदी, मराठी, ಕನ್ನಡ ও বাংলা-এর মধ্যে "
               "বদলান। আমিও আপনার নির্বাচিত ভাষায় উত্তর দেব।"),
    },
    "statuses": {
        "en": ("JanSetu complaints move through these statuses:\n"
               "• Pending Validation — submitted, waiting for a validator to review the evidence.\n"
               "• Verified — a validator confirmed it is genuine; it moves to the official department.\n"
               "• Resolved — the department acted on it and marked it resolved.\n"
               "• Rejected — the validator could not confirm it; check the remarks for the reason."),
        "hi": ("JanSetu शिकायतें इन स्थितियों से गुजरती हैं:\n"
               "• सत्यापन लंबित — जमा हुई, सत्यापनकर्ता साक्ष्य की जाँच कर रहा है।\n"
               "• सत्यापित — सत्यापनकर्ता ने पुष्टि की; यह अधिकारी विभाग को जाती है।\n"
               "• हल हो गई — विभाग ने कार्रवाई कर समाधान चिह्नित किया।\n"
               "• अस्वीकृत — सत्यापन नहीं हो सका; कारण टिप्पणियों में देखें।"),
        "mr": ("JanSetu तक्रारी या स्थितींमधून जातात:\n"
               "• पडताळणी प्रलंबित — सादर, पडताळणीकर्ता पुरावा तपासत आहे.\n"
               "• सत्यापित — पडताळणीकर्त्याने पुष्टी केली; ती विभागाकडे जाते.\n"
               "• सोडवले — विभागाने कारवाई करून सोडवले चिन्हांकित केले.\n"
               "• फेटाळले — पुष्टी होऊ शकली नाही; कारण शेऱ्यांमध्ये पहा."),
        "kn": ("JanSetu ದೂರುಗಳು ಈ ಸ್ಥಿತಿಗಳ ಮೂಲಕ ಹೋಗುತ್ತವೆ:\n"
               "• ಪರಿಶೀಲನೆ ಬಾಕಿ — ಸಲ್ಲಿಸಲಾಗಿದೆ, ಪರಿಶೀಲಕ ಸಾಕ್ಷ್ಯವನ್ನು ಪರಿಶೀಲಿಸುತ್ತಿದ್ದಾರೆ.\n"
               "• ಪರಿಶೀಲಿಸಲಾಗಿದೆ — ಪರಿಶೀಲಕ ದೃಢಪಡಿಸಿದ್ದಾರೆ; ಅಧಿಕಾರಿ ಇಲಾಖೆಗೆ ಹೋಗುತ್ತದೆ.\n"
               "• ಪರಿಹರಿಸಲಾಗಿದೆ — ಇಲಾಖೆ ಕ್ರಮ ತೆಗೆದುಕೊಂಡು ಪರಿಹರಿಸಲಾಗಿದೆ ಎಂದು ಗುರುತಿಸಿದೆ.\n"
               "• ತಿರಸ್ಕರಿಸಲಾಗಿದೆ — ದೃಢೀಕರಿಸಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ; ಟಿಪ್ಪಣಿಯಲ್ಲಿ ಕಾರಣ ನೋಡಿ."),
        "bn": ("JanSetu অভিযোগ এই অবস্থাগুলোর মধ্য দিয়ে যায়:\n"
               "• যাচাইকরণ বাকি — জমা হয়েছে, যাচাইকারী প্রমাণ পরীক্ষা করছেন।\n"
               "• যাচাইকৃত — যাচাইকারী নিশ্চিত করেছেন; এটি বিভাগে যায়।\n"
               "• সমাধান হয়েছে — বিভাগ ব্যবস্থা নিয়ে সমাধান চিহ্নিত করেছে।\n"
               "• বাতিল — নিশ্চিত করা যায়নি; মন্তব্যে কারণ দেখুন।"),
    },
    "my_data": {
        "en": ("I don't have access to your personal account data here. To see your own "
               "complaint IDs, statuses or history, please check your Dashboard → My "
               "Complaints. If you share a Complaint ID (like JST-4K9XM2P7) with me, I "
               "can look up its status live."),
        "hi": ("मेरे पास आपके निजी खाते का डेटा नहीं है। अपनी शिकायत आईडी, स्थिति या इतिहास के "
               "लिए डैशबोर्ड → मेरी शिकायतें देखें। अगर आप मुझे शिकायत आईडी (जैसे JST-4K9XM2P7) "
               "बताएँ तो मैं उसकी स्थिति लाइव देख सकता हूँ।"),
        "mr": ("माझ्याकडे तुमचा खाजगी खाते डेटा नाही. तुमच्या तक्रारी पाहण्यासाठी डॅशबोर्ड → माझ्या "
               "तक्रारी उघडा. तक्रार आयडी (जसे JST-4K9XM2P7) दिल्यास मी तिची स्थिती लाइव पाहू शकतो."),
        "kn": ("ನಿಮ್ಮ ವೈಯಕ್ತಿಕ ಖಾತೆ ಡೇಟಾ ನನ್ನ ಬಳಿ ಇಲ್ಲ. ನಿಮ್ಮ ದೂರುಗಳಿಗೆ ಡ್ಯಾಶ್ಬೋರ್ಡ್ → ನನ್ನ "
               "ದೂರುಗಳು ನೋಡಿ. ದೂರು ID (JST-4K9XM2P7 ರೀತಿ) ಹೇಳಿದರೆ ನಾನು ಅದರ ಸ್ಥಿತಿಯನ್ನು ಲೈವ್ ಪರಿಶೀಲಿಸಬಲ್ಲೆ."),
        "bn": ("আপনার ব্যক্তিগত অ্যাকাউন্ট ডেটা আমার কাছে নেই। নিজের অভিযোগ দেখতে ড্যাশবোর্ড → আমার "
               "অভিযোগ দেখুন। অভিযোগ ID (যেমন JST-4K9XM2P7) জানালে আমি এর অবস্থা লাইভ দেখে দিতে পারি।"),
    },
    "greeting": {
        "en": "Hello! 👋 How can I help you today? You can ask me about filing complaints, tracking status, complaint IDs, PINs, photo and GPS evidence, or the verification workflow.",
        "hi": "नमस्ते! 👋 आज मैं आपकी कैसे मदद करूँ? आप शिकायत दर्ज करने, स्थिति ट्रैक करने, शिकायत आईडी, PIN, फोटो/GPS साक्ष्य या सत्यापन प्रक्रिया के बारे में पूछ सकते हैं।",
        "mr": "नमस्कार! 👋 आज मी तुमची कशी मदत करू? तक्रार नोंदणी, स्थिती ट्रॅकिंग, तक्रार आयडी, PIN, फोटो/GPS पुरावा किंवा पडताळणी प्रक्रियेबद्दल विचारू शकता.",
        "kn": "ನಮಸ್ಕಾರ! 👋 ಇಂದು ನಾನು ನಿಮಗೆ ಹೇಗೆ ಸಹಾಯ ಮಾಡಲಿ? ದೂರು ಸಲ್ಲಿಸುವುದು, ಸ್ಥಿತಿ ಟ್ರ್ಯಾಕಿಂಗ್, ದೂರು ID, PIN, ಫೋಟೋ/GPS ಸಾಕ್ಷ್ಯ ಅಥವಾ ಪರಿಶೀಲನಾ ಪ್ರಕ್ರಿಯೆಯ ಬಗ್ಗೆ ಕೇಳಬಹುದು.",
        "bn": "হ্যালো! 👋 আজ আমি আপনাকে কীভাবে সাহায্য করতে পারি? অভিযোগ দাখিল, অবস্থা ট্র্যাকিং, অভিযোগ ID, PIN, ছবি/GPS প্রমাণ বা যাচাই প্রক্রিয়া সম্পর্কে জিজ্ঞাসা করতে পারেন।",
    },
    "thanks": {
        "en": "You're welcome! 😊 Is there anything else I can help you with?",
        "hi": "आपका स्वागत है! 😊 क्या मैं और कुछ मदद कर सकता हूँ?",
        "mr": "आपले स्वागत आहे! 😊 आणखी काही मदत करू का?",
        "kn": "ಸ್ವಾಗತ! 😊 ಇನ್ನೇನಾದರೂ ಸಹಾಯ ಬೇಕೇ?",
        "bn": "স্বাগতম! 😊 আরও কিছু সাহায্য করতে পারি?",
    },
    "default": {
        "en": ("I'm sorry, I couldn't find a clear answer to that. I can help with: how "
               "to file or track a complaint, complaint IDs & PINs, photo and GPS "
               "evidence, the validation workflow, status meanings and urgency scores. "
               "Try one of the quick questions, or ask me in a different way."),
        "hi": ("क्षमा करें, मुझे इसका स्पष्ट उत्तर नहीं मिला। मैं इनमें मदद कर सकता हूँ: शिकायत "
               "दर्ज करना या ट्रैक करना, शिकायत आईडी और PIN, फोटो/GPS साक्ष्य, सत्यापन प्रक्रिया, "
               "स्थिति के अर्थ और तात्कालिकता स्कोर। कृपया अलग तरीके से पूछें।"),
        "mr": ("माफ करा, मला याचे स्पष्ट उत्तर सापडले नाही. तक्रार नोंदणी/ट्रॅकिंग, तक्रार आयडी "
               "आणि PIN, फोटो/GPS पुरावा, पडताळणी प्रक्रिया, स्थितीचे अर्थ आणि तातडीचेपणा स्कोर "
               "याबद्दल मी मदत करू शकतो."),
        "kn": ("ಕ್ಷಮಿಸಿ, ಅದಕ್ಕೆ ಸ್ಪಷ್ಟ ಉತ್ತರ ಸಿಗಲಿಲ್ಲ. ದೂರು ಸಲ್ಲಿಸುವುದು/ಟ್ರ್ಯಾಕ್ ಮಾಡುವುದು, ದೂರು ID "
               "ಮತ್ತು PIN, ಫೋಟೋ/GPS ಸಾಕ್ಷ್ಯ, ಪರಿಶೀಲನಾ ಪ್ರಕ್ರಿಯೆ, ಸ್ಥಿತಿಯ ಅರ್ಥ ಮತ್ತು ತುರ್ತು ಸ್ಕೋರ್ "
               "ಬಗ್ಗೆ ನಾನು ಸಹಾಯ ಮಾಡಬಲ್ಲೆ."),
        "bn": ("দুঃখিত, এর স্পষ্ট উত্তর আমি পাইনি। অভিযোগ দাখিল/ট্র্যাকিং, অভিযোগ ID ও PIN, ছবি/GPS "
               "প্রমাণ, যাচাই প্রক্রিয়া, অবস্থার অর্থ এবং জরুরিতা স্কোর সম্পর্কে আমি সাহায্য করতে পারি।"),
    },
}

# ---------------------------------------------------------------------------
# Keyword matchers — topic → phrases (English + all four Indian languages).
# ---------------------------------------------------------------------------
KEYWORDS = {
    "greeting": ["hello", "hi ", "hey", "namaste", "namaskar", "नमस्ते", "नमस्कार",
                 "हॅलो", "ಹಲೋ", "ನಮಸ್ಕಾರ", "হ্যালো", "নমস্কার"],
    "thanks": ["thank", "thanks", "धन्यवाद", "थँक्स", "धन्यवाद", "ಶುಕ್ರಿಯ", "ধন্যবাদ", "धन्यवाद्"],
    "track": ["track", "status", "where is my complaint", "complaint status", "update on my",
              "ट्रैक", "स्थिति", "मेरी शिकायत", "ट्रॅक", "स्थिती", "माझी तक्रार",
              "ಟ್ರ್ಯಾಕ್", "ಸ್ಥಿತಿ", "ನನ್ನ ದೂರು", "ট্র্যাক", "অবস্থা", "আমার অভিযোগ"],
    "submit": ["file a complaint", "submit a complaint", "how do i complain", "how to complain",
               "raise a complaint", "register a complaint", "file complaint",
               "शिकायत दर्ज", "शिकायत कैसे", "कैसे करें", "शिकायत करें",
               "तक्रार नोंदव", "तक्रार कशी", "दूರು ಸಲ್ಲಿಸಿ", "ದೂರು ಸಲ್ಲಿಸುವುದು", "ಹೇಗೆ",
               "অভিযোগ দাখিল", "কীভাবে অভিযোগ", "অভিযোগ কীভাবে"],
    "complaint_id": ["complaint id", "complaint number", "reference number", "what is my id",
                     "शिकायत आईडी", "शिकायत नंबर", "तक्रार आयडी", "दूರು ID", "অভিযোগ ID"],
    "pin": ["pin", "पिन", "पीआईएन", "पीएन", "PIN"],
    "photo": ["photo", "picture", "image", "evidence photo", "upload photo",
              "फोटो", "तस्वीर", "छायाचित्र", "ಫೋಟೋ", "ছবি"],
    "gps": ["gps", "location", "latitude", "longitude", "गूगल मैप", "लोकेशन", "जीपीएस",
            "ಸ್ಥಳ", "ಜಿಪಿಎಸ್", "অবস্থান", "জিপিএস"],
    "after_submit": ["what happens after", "what happens next", "after submitting", "next step",
                     "बाद में क्या", "आगे क्या", "नंतर काय", "ನಂತರ ಏನು", "এরপর কী"],
    "pending": ["pending", "लंबित", "प्रलंबित", "ಬಾಕಿ", "বাকি"],
    "verified": ["verified", "verify", "सत्यापित", "सत्यापन", "पडताळणी", "ಪರಿಶೀಲಿಸಲಾಗಿದೆ", "যাচাইকৃত"],
    "resolved": ["resolved", "resolution", "solution", "हल", "समाधान", "सोडवले", "पರಿಹರಿಸಲಾಗಿದೆ", "সমাধান"],
    "rejected": ["reject", "rejected", "अस्वीकृत", "फेटाळले", "तिरस्कರಿಸಲಾಗಿದೆ", "বাতিল"],
    "time": ["how long", "how much time", "processing time", "how many days", "take time",
             "कितना समय", "कितने दिन", "किती वेळ", "किती दिवस", "ಎಷ್ಟು ದಿನ", "কত দিন", "কত সময়"],
    "department": ["department", "officer", "authority", "contact", "helpline", "विभाग",
                   "अधिकारी", "संपर्क", "इलಾಖೆ", "অধিকারী", "বিভাগ", "যোগাযোগ"],
    "edit": ["edit", "change my complaint", "update my complaint", "संपादित", "बदलना",
             "बदलू", "ಬದಲಾಯಿಸಿ", "সংশোধন"],
    "history": ["history", "my complaints", "previous complaints", "list of complaints",
                "मेरी शिकायतें", "माझ्या तक्रारी", "ನನ್ನ ದೂರುಗಳು", "আমার অভিযোগ"],
    "urgency": ["urgency", "urgent", "priority", "score", "तात्कालिकता", "तातडीचेपणा",
                "ತುರ್ತು", "জরুরি", "জরুরিতা"],
    "statuses": ["status meaning", "status meanings", "statuses", "what do the statuses",
                 "status labels", "स्थितियों के अर्थ", "स्थितीचे अर्थ", "ಸ್ಥಿತಿಯ ಅರ್ಥ", "অবস্থার অর্থ"],
    "ai": ["ai", "artificial intelligence", "gemini", "privacy", "pii", "transcribe",
           "एआई", "जेमिनी", "गोपनीयता", "आर्टिफिशियल", "कृत्रिम", "कृत्रिम बुद्धिमत्ता",
           "ಗೈಮಿನಿ", "ಎಐ", "গোপনীয়তা", "এআই", "জেমিনি"],
    "location": ["why location", "location required", "लोकेशन क्यों", "लोकेशन जरूरी",
                 "स्थಳ ಏಕೆ", "অবস্থান কেন"],
    "language": ["language", "change language", "hindi", "marathi", "kannada", "bengali",
                 "भाषा", "हिंदी", "मराठी", "ಕನ್ನಡ", "বাংলা"],
    "my_data": ["my complaint id", "my pin", "my account", "my phone", "my name", "who am i",
                "मेरी शिकायत आईडी", "मेरा खाता", "माझी तक्रार आयडी", "माझे खाते",
                "ನನ್ನ ದೂರು ID", "ನನ್ನ ಖಾತೆ", "আমার অভিযোগ ID", "আমার অ্যাকাউন্ট"],
}


def _score_topic(message: str) -> tuple:
    """Return the best-matching topic (and its score) for a message."""
    norm = _norm(message)
    best_topic, best_score = "default", 0
    for topic, phrases in KEYWORDS.items():
        score = 0
        for phrase in phrases:
            if phrase in norm:
                # Longer phrases are stronger signals than single words.
                score += 2 if len(phrase.split()) > 1 else 1
        if score > best_score:
            best_topic, best_score = topic, score
    return best_topic, best_score


def mock_chat_response(message: str, language: str = "en") -> str:
    """Pick a citizen-friendly answer for a message using the local KB.

    Works entirely offline; used when Gemini is unavailable or fails.
    """
    lang = language if language in LANGUAGES else "en"
    topic, _score = _score_topic(message)
    return KB.get(topic, KB["default"])[lang]


# ---------------------------------------------------------------------------
# Live complaint-status replies (data is NEVER fabricated — only returned when
# a matching complaint actually exists in the database).
# ---------------------------------------------------------------------------
def status_ask_id_reply(language: str = "en") -> str:
    lang = language if language in LANGUAGES else "en"
    return {
        "en": ("I can check your complaint's status live. Please share your Complaint ID "
               "(it looks like JST-4K9XM2P7)."),
        "hi": ("मैं आपकी शिकायत की स्थिति लाइव जाँच सकता हूँ। कृपया अपनी शिकायत आईडी "
               "(जैसे JST-4K9XM2P7) बताएँ।"),
        "mr": ("मी तुमच्या तक्रारीची स्थिती लाइव तपासू शकतो. कृपया तक्रार आयडी (जसे "
               "JST-4K9XM2P7) द्या."),
        "kn": ("ನಿಮ್ಮ ದೂರಿನ ಸ್ಥಿತಿಯನ್ನು ನಾನು ಲೈವ್ ಪರಿಶೀಲಿಸಬಲ್ಲೆ. ದಯವಿಟ್ಟು ನಿಮ್ಮ ದೂರು ID "
               "(JST-4K9XM2P7 ರೀತಿ) ಹೇಳಿ."),
        "bn": ("আমি আপনার অভিযোগের অবস্থা লাইভ দেখতে পারি। অনুগ্রহ করে আপনার অভিযোগ ID "
               "(যেমন JST-4K9XM2P7) দিন।"),
    }[lang]


def status_not_found_reply(complaint_id: str, language: str = "en") -> str:
    lang = language if language in LANGUAGES else "en"
    return {
        "en": (f"I couldn't find a complaint with the ID {complaint_id}. Please double-"
               f"check the ID (format: JST-XXXXXXXX) and try again."),
        "hi": (f"मुझे {complaint_id} आईडी वाली शिकायत नहीं मिली। कृपया आईडी जाँचें "
               f"(प्रारूप: JST-XXXXXXXX) और फिर से प्रयास करें।"),
        "mr": (f"मला {complaint_id} या आयडीची तक्रार सापडली नाही. कृपया आयडी तपासा "
               f"(प्रारूप: JST-XXXXXXXX)."),
        "kn": (f"{complaint_id} ID ಇರುವ ದೂರು ಸಿಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ID ಪರಿಶೀಲಿಸಿ "
               f"(ಸ್ವರೂಪ: JST-XXXXXXXX)."),
        "bn": (f"{complaint_id} আইডির অভিযোগ খুঁজে পাইনি। অনুগ্রহ করে ID যাচাই করুন "
               f"(ফরম্যাট: JST-XXXXXXXX)।"),
    }[lang]


def status_found_reply(complaint, is_owner: bool, language: str = "en") -> str:
    """Build a status reply from a real Complaint document (never invented).

    Privacy: only the owner sees the AI summary; everyone else only sees the
    public tracking fields (ID, status, category, urgency, date).
    """
    from apps.core.utils import utc_to_ist

    lang = language if language in LANGUAGES else "en"
    status_label = STATUS_LABELS.get(complaint.status, {}).get(lang, complaint.status.replace("_", " ").title())
    created_ist = utc_to_ist(complaint.created_at)

    lines = {
        "en": [
            f"Here is your complaint's current status:",
            f"• Complaint ID: {complaint.complaint_id}",
            f"• Status: {status_label}",
            f"• Category: {complaint.category}",
            f"• Urgency: {complaint.urgency_score}/10",
            f"• Submitted: {created_ist:%d %b %Y, %I:%M %p}",
        ],
        "hi": [
            f"आपकी शिकायत की वर्तमान स्थिति:",
            f"• शिकायत आईडी: {complaint.complaint_id}",
            f"• स्थिति: {status_label}",
            f"• श्रेणी: {complaint.category}",
            f"• तात्कालिकता: {complaint.urgency_score}/10",
            f"• जमा की गई: {created_ist:%d %b %Y, %I:%M %p}",
        ],
        "mr": [
            f"तुमच्या तक्रारीची सध्याची स्थिती:",
            f"• तक्रार आयडी: {complaint.complaint_id}",
            f"• स्थिती: {status_label}",
            f"• श्रेणी: {complaint.category}",
            f"• तातडीचेपणा: {complaint.urgency_score}/10",
            f"• सादर केली: {created_ist:%d %b %Y, %I:%M %p}",
        ],
        "kn": [
            f"ನಿಮ್ಮ ದೂರಿನ ಪ್ರಸ್ತುತ ಸ್ಥಿತಿ:",
            f"• ದೂರು ID: {complaint.complaint_id}",
            f"• ಸ್ಥಿತಿ: {status_label}",
            f"• ವರ್ಗ: {complaint.category}",
            f"• ತುರ್ತು: {complaint.urgency_score}/10",
            f"• ಸಲ್ಲಿಸಿದ ದಿನಾಂಕ: {created_ist:%d %b %Y, %I:%M %p}",
        ],
        "bn": [
            f"আপনার অভিযোগের বর্তমান অবস্থা:",
            f"• অভিযোগ ID: {complaint.complaint_id}",
            f"• অবস্থা: {status_label}",
            f"• ক্যাটাগরি: {complaint.category}",
            f"• জরুরিতা: {complaint.urgency_score}/10",
            f"• জমার তারিখ: {created_ist:%d %b %Y, %I:%M %p}",
        ],
    }[lang]

    if is_owner and complaint.summary:
        lines.append({
            "en": f"• AI summary: {complaint.summary}",
            "hi": f"• AI सारांश: {complaint.summary}",
            "mr": f"• AI सारांश: {complaint.summary}",
            "kn": f"• AI ಸಾರಾಂಶ: {complaint.summary}",
            "bn": f"• AI সারাংশ: {complaint.summary}",
        }[lang])

    lines.append({
        "en": "You can open the full details, timeline and remarks from your Dashboard → My Complaints.",
        "hi": "पूरे विवरण, समयरेखा और टिप्पणियाँ डैशबोर्ड → मेरी शिकायतें में देख सकते हैं।",
        "mr": "पूर्ण तपशील, टाइमलाइन आणि शेरे डॅशबोर्ड → माझ्या तक्रारी मध्ये पाहू शकता.",
        "kn": "ಪೂರ್ಣ ವಿವರ, ಟೈಮ್‌ಲೈನ್ ಮತ್ತು ಟಿಪ್ಪಣಿಗಳನ್ನು ಡ್ಯಾಶ್ಬೋರ್ಡ್ → ನನ್ನ ದೂರುಗಳು ನಲ್ಲಿ ನೋಡಬಹುದು.",
        "bn": "সম্পূর্ণ বিবরণ, টাইমলাইন ও মন্তব্য ড্যাশবোর্ড → আমার অভিযোগ-এ দেখতে পারবেন।",
    }[lang])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Complaint-ID detection
# ---------------------------------------------------------------------------
COMPLAINT_ID_RE = re.compile(r"\b(JST-[A-Z0-9]{8})\b")


def extract_complaint_id(message: str):
    """Return the first JST-XXXXXXXX ID found in a message, else None."""
    match = COMPLAINT_ID_RE.search((message or "").upper())
    return match.group(1) if match else None
