# Microsoft Store submission: what to paste where

Partner Center → UbiClipper → submission. Everything below can be pasted as is.

## Properties

- **Category:** Photo & video
- **Privacy policy URL:** https://uberbora.github.io/ubiclipper/privacy/
- **Website:** https://uberbora.github.io/ubiclipper/
- **Support contact:** uberyastudios@gmail.com

## Pricing and availability

- **Price:** Free · **Markets:** all

## Age ratings

Answer the questionnaire: no violence, no user-to-user communication inside the
app, no purchases, no location sharing. Note: the app can upload the user's own
clips to their own TikTok / Instagram / YouTube accounts.

## Restricted capability: runFullTrust (justification)

> UbiClipper is a classic Win32 desktop app (Python with a Tk window). It runs
> FFmpeg and local AI models on the user's PC to cut and subtitle video files
> the user opens, so it needs to run as a full-trust desktop application.

## Store listing: English

**Description**

UbiClipper finds the funny moments in your stream and turns them into subtitled
9:16 clips for TikTok, Instagram Reels and YouTube Shorts.

Open a video, or paste a Kick, Twitch or YouTube link, and press Analyze.
UbiClipper listens for laughter, screams, explosions and sudden shouting, reads
what was said and how chat reacted, and a local AI judge rates each moment.
Untick what you don't want and export: every clip comes with your webcam on top,
the game below and subtitles in between, plus a 1920×1080 copy for montages.

- Subtitles in Turkish and more than 30 other languages, with a colour per person
- Fix any word, line or speaker by hand; trim clips on a timeline
- Place subtitles where TikTok, Reels and Shorts buttons won't cover them
- Post to TikTok, Instagram Reels and YouTube Shorts in one go
- Free, no account, no watermark. The AI runs on your own PC; your videos never
  leave it unless you post them.

**Short description:** Finds the funny moments in your stream and cuts them into subtitled 9:16 clips.

**Keywords:** stream clips, twitch clipper, kick clips, auto subtitles, shorts maker

**What's new:** First Microsoft Store release.

## Store listing: Türkçe

**Açıklama**

UbiClipper yayınındaki komik anları bulur ve TikTok, Instagram Reels ve YouTube
Shorts için altyazılı 9:16 kliplere çevirir.

Bir video aç ya da bir Kick, Twitch veya YouTube linki yapıştır ve Analiz et'e
bas. UbiClipper kahkahaları, çığlıkları, patlamaları ve ani bağırışları dinler,
ne söylendiğini ve chat'in nasıl tepki verdiğini okur; yerel bir AI hakem her
anı puanlar. İstemediklerinin işaretini kaldır ve dışa aktar: her klipte üstte
kameran, altta oyun ve aralarında altyazı olur; montajlar için 1920×1080 bir
kopya da gelir.

- Türkçe ve 30'dan fazla dilde altyazı, herkes için ayrı renk
- Her kelimeyi, satırı ve konuşmacıyı elle düzelt; klipleri zaman çizelgesinde kırp
- Altyazıları TikTok, Reels ve Shorts butonlarının kapatmayacağı yere yerleştir
- TikTok, Instagram Reels ve YouTube Shorts'a tek seferde paylaş
- Ücretsiz, hesap yok, filigran yok. AI kendi bilgisayarında çalışır; videoların
  sen paylaşmadıkça bilgisayarından çıkmaz.

**Kısa açıklama:** Yayınındaki komik anları bulur, altyazılı 9:16 kliplere çevirir.

## Screenshots

At least one, 1920×1080 or 1366×768 PNG: the clip list after Analyze, the 9:16
tab with the subtitle placer, and a finished clip.

## Package

Download **ubiclipper-windows** from the latest successful run of *Build Windows
installer* (Actions tab) and upload the `.msix` inside. It is built with the
Product identity values in `packaging/msix/store_identity.json`
(`Name`, `Publisher`, `PublisherDisplayName` from Partner Center → Product
identity).
