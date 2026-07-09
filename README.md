# Raylogic H81 Dimmer - Home Assistant Integration

Raylogic DIN-H81 (8-channel dimmer) panels ko Home Assistant mein add karne
ke liye. Setup **UI se hota hai** - koi YAML edit nahi karna padta. Har
panel ke liye sirf **IP Address** aur **Start Address** dena hai; baaki sab
(8 channel numbers, unke hex addresses, TCP connection, mobile-app feedback
sync) khud ho jaata hai.

## Install via HACS

1. HACS -> ... (top-right menu) -> **Custom repositories**.
2. Repository URL daalo (jahan ye code push kiya hai), category **Integration** select karo, **Add**.
3. HACS mein "Raylogic H81 Dimmer" search karke **Download** karo.
4. Home Assistant **restart** karo.

## Panel Add Karo (sirf IP + Start Address)

1. **Settings -> Devices & Services -> Add Integration**.
2. "**Raylogic H81**" search karo.
3. Form mein bas 2 cheezein bharo:
   - **IP Address** - panel ka IP (jaise `192.168.120.100`)
   - **Start Address** - Raylogic GO app > Device Info screen se
     ("Start address: 0x0101" jaisa dikhta hai - `0101`, `0x0101`, ya
     decimal `257` kisi bhi format mein daal sakte ho)
4. **Submit** karo - panel ke 8 dimmer channels turant HA mein light entities
   ban jaayenge.

Ek aur panel add karna ho to **Add Integration** dubara use karo, uska bhi
sirf IP + Start Address dena hoga.

> Port (`5550`), Area (`02`), aur Device-ID (`2`) automatically set ho jaate
> hain - saare panels normally inhi values pe hote hain. Agar kisi panel ka
> Docklight capture alag dikhaye, to us panel ki integration entry pe jaake
> **Configure** (Options) se override kar sakte ho.

## Start Address kaha se milega

Raylogic GO app kholo -> apna panel select karo -> Device Info screen pe
"**Start address**" field dikhega (jaisa `0x0101`). Wahi value yahan daalni
hai.

**Ye network se auto-detect nahi ho sakta**: Raylogic GO Protocol v0.4
(official PDF) ke QUERY DEVICE command mein bhi start address khud
**input** ke roop mein dena padta hai - protocol mein koi "scan/discover
saare devices" command hai hi nahi. Isliye ye value ek baar app se dekhna
zaroori hai, uske baad sab kuch automatic hai.

## Kaise kaam karta hai (short version)

- Start address (jaise `0x0101` = decimal `257`) se 8 channel numbers
  calculate hote hain: `257, 258, 259, ... 264`.
- Har channel number apne 2-byte hex address mein todha jaata hai (high/low
  byte) - Raylogic GO Protocol v0.4 ke "AREA CHANNEL DIRECT" command format
  mein bhejne ke liye.
- Har panel (IP:Port) ka apna persistent TCP connection hai, apna
  sequence-number counter, aur apne listeners - taaki mobile app se
  ON/OFF/dimming karne par bhi HA turant sync ho jaye.

## Files

```
custom_components/raylogic_h81/
├── __init__.py       - integration setup/unload
├── config_flow.py     - UI form (IP + Start Address)
├── const.py            - shared constants/defaults
├── light.py             - light entities, start-address -> channels calc
├── protocol.py           - TCP driver (Raylogic GO Protocol v0.4)
├── manifest.json
├── strings.json / translations/en.json  - UI text
```

## License

MIT - dekho `LICENSE` file.
