import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go
import json
import numpy as np
import gspread
from google.oauth2.service_account import Credentials

# 1. Konfiguracja strony
st.set_page_config(
    page_title="Mój Portfel", 
    page_icon="https://img.icons8.com/fluency/96/portfolio.png", 
    layout="wide"
)

st.markdown("""
    <style>
    .stMetric { background-color: rgba(255, 255, 255, 0.05); padding: 15px; border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

# 2. Połączenie z Google Sheets
@st.cache_resource
def polacz_z_baza():
    try:
        klucz_json = json.loads(st.secrets["gcp_service_account_json"], strict=False)
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(klucz_json, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open("MyGotuwa")
        return sh
    except Exception as e:
        st.error(f"Błąd logowania do Google Sheets. Sprawdź klucz JSON. Szczegóły: {e}")
        st.stop()

sh = polacz_z_baza()
ws_transakcje = sh.worksheet("Transakcje")
ws_portfele = sh.worksheet("Portfele")
ws_waluty = sh.worksheet("Waluty")
ws_tickery = sh.worksheet("Tickery")

def pobierz_liste(ws):
    dane = ws.col_values(1)
    return [d for d in dane if d.strip() != ""]

def nadpisz_liste(ws, nowa_lista):
    ws.clear()
    if nowa_lista:
        ws.append_rows([[x] for x in nowa_lista])

ustawienia = {
    "portfele": pobierz_liste(ws_portfele),
    "waluty": pobierz_liste(ws_waluty),
    "tickery": pobierz_liste(ws_tickery)
}
if not ustawienia["portfele"]: ustawienia["portfele"] = ["Główny"]
if not ustawienia["waluty"]: ustawienia["waluty"] = ["PLN"]
if not ustawienia["tickery"]: ustawienia["tickery"] = ["AAPL"]

# --- Funkcja pomocnicza giełdy ---
@st.cache_data(ttl=3600, show_spinner="Pobieranie danych z giełdy...")
def pobierz_historie_notowan(tickery, start_date):
    if not tickery: return pd.DataFrame()
    symbole = list(set(tickery + ['^GSPC', 'PLN=X', 'EURPLN=X']))
    dane = yf.download(symbole, start=start_date, progress=False)
    if isinstance(dane.columns, pd.MultiIndex):
        dane_close = dane['Close']
    else:
        if 'Close' in dane.columns:
            dane_close = pd.DataFrame({symbole[0]: dane['Close']})
        else:
            dane_close = dane
    return dane_close.ffill().bfill()

# Pobranie transakcji z chmury
dane_transakcji = ws_transakcje.get_all_records()
WYMAGANE_KOLUMNY = ["Data", "Portfel", "Ticker", "Nazwa", "Typ", "Ilosc", "Cena_Zakupu", "Waluta"]
if dane_transakcji:
    df = pd.DataFrame(dane_transakcji)
    df['Ilosc'] = pd.to_numeric(df['Ilosc'], errors='coerce')
    df['Cena_Zakupu'] = pd.to_numeric(df['Cena_Zakupu'], errors='coerce')
else:
    df = pd.DataFrame(columns=WYMAGANE_KOLUMNY)

# 3. Kursy walut
st.sidebar.title(":material/currency_exchange: Kursy walut")
kursy = {"PLN": 1.0}
blad_pobierania = False

for waluta in ustawienia["waluty"]:
    if waluta == "PLN": continue
    try:
        ticker_waluty = f"{waluta}PLN=X" 
        kurs = yf.Ticker(ticker_waluty).history(period="1d")['Close'].iloc[0]
        kursy[waluta] = kurs
        st.sidebar.metric(label=f"{waluta} / PLN", value=f"{kurs:.4f} zł")
    except:
        blad_pobierania = True
        awaryjne = {"USD": 4.00, "EUR": 4.30, "GBP": 5.00, "CHF": 4.50}
        kursy[waluta] = awaryjne.get(waluta, 1.0)
        st.sidebar.metric(label=f"{waluta} / PLN", value=f"{kursy[waluta]:.4f} zł", delta="Błąd sieci", delta_color="inverse")

if blad_pobierania: st.sidebar.warning(":material/wifi_off: Tryb Offline")
else: st.sidebar.success(":material/wifi: Kursy na żywo (Online)")
st.sidebar.divider()
st.sidebar.info(":material/info: Waluty przeliczane na PLN po bieżącym kursie.")

st.title(":material/monitoring: Twój Panel Inwestycyjny")

tab1, tab2, tab3, tab4 = st.tabs([
    ":material/dashboard: Dashboard", 
    ":material/add_circle: Dodaj transakcję",
    ":material/history: Historia",
    ":material/settings: Ustawienia"
])

# --- ZAKŁADKA 2: DODAWANIE TRANSAKCJI ---
with tab2:
    st.header("Zarejestruj nową operację")
    with st.form("dodaj_transakcje", clear_on_submit=True):
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            data_operacji = st.date_input("Data operacji")
            portfel = st.selectbox("Wybierz portfel", ustawienia["portfele"])
            opcje_tickerow = ["➕ Dodaj nowy..."] + ustawienia["tickery"]
            wybrany_ticker = st.selectbox("Ticker", opcje_tickerow)
            
        with col2:
            st.write(""); st.write("")
            nowy_ticker = st.text_input("Nowy Ticker (jeśli wybrano ➕)")
            nazwa = st.text_input("Nazwa aktywa")
            
        with col3:
            st.write(""); st.write("")
            typ = st.selectbox("Typ operacji", ["KUPNO", "SPRZEDAŻ"])
            ilosc = st.number_input("Ilość", min_value=0.00001, format="%.5f")
            
        with col4:
            st.write(""); st.write("")
            waluta = st.selectbox("Waluta transakcji", ustawienia["waluty"])
            cena = st.number_input("Cena za sztukę", min_value=0.01)
            st.write("") 
            zapisz = st.form_submit_button(":material/save: Zapisz do portfela")

        if zapisz:
            docelowy_ticker = nowy_ticker.upper().strip() if wybrany_ticker == "➕ Dodaj nowy..." else wybrany_ticker
            if docelowy_ticker == "":
                st.error("Podaj poprawny ticker!")
            else:
                if docelowy_ticker not in ustawienia["tickery"]:
                    ustawienia["tickery"].append(docelowy_ticker)
                    nadpisz_liste(ws_tickery, ustawienia["tickery"])
                
                ws_transakcje.append_row([
                    data_operacji.strftime("%Y-%m-%d"), 
                    portfel, 
                    docelowy_ticker, 
                    nazwa, 
                    typ, 
                    float(ilosc if typ == "KUPNO" else -ilosc), 
                    float(cena), 
                    waluta
                ])
                st.success(f"Dodano {typ} dla {docelowy_ticker} w chmurze!")
                st.cache_data.clear() 
                st.rerun()

# --- ZAKŁADKA 3: HISTORIA ---
with tab3:
    st.header("Pełna historia operacji")
    st.write("Edytuj dane i zapisz zmiany do chmury.")
    if not df.empty:
        df_historia = df.sort_values(by="Data", ascending=False)
        edytowany_df = st.data_editor(df_historia, use_container_width=True, num_rows="dynamic", hide_index=True)
        if st.button(":material/save: Zapisz zmiany w Google Sheets"):
            ws_transakcje.clear()
            ws_transakcje.append_row(WYMAGANE_KOLUMNY)
            dane_do_zapisu = edytowany_df.fillna("").values.tolist()
            if dane_do_zapisu:
                ws_transakcje.append_rows(dane_do_zapisu)
            st.success("Baza zaktualizowana w chmurze!")
            st.cache_data.clear()
            st.rerun()
    else:
        st.info("Brak transakcji w chmurze.")

# --- ZAKŁADKA 4: USTAWIENIA ---
with tab4:
    col_portfele, col_waluty, col_tickery = st.columns(3)
    
    with col_portfele:
        st.subheader(":material/folder_open: Portfele")
        st.write(", ".join(ustawienia["portfele"]))
        nowy_portfel = st.text_input("Nowy portfel")
        if st.button("Dodaj portfel") and nowy_portfel not in ustawienia["portfele"]:
            ustawienia["portfele"].append(nowy_portfel.strip())
            nadpisz_liste(ws_portfele, ustawienia["portfele"])
            st.rerun()
        st.divider()
        portfel_usun = st.selectbox("Wybierz do usunięcia", ustawienia["portfele"], key="del_portfel")
        if st.button(":material/delete: Usuń portfel") and portfel_usun:
            ustawienia["portfele"].remove(portfel_usun)
            nadpisz_liste(ws_portfele, ustawienia["portfele"])
            st.rerun()

    with col_waluty:
        st.subheader(":material/payments: Waluty")
        st.write(", ".join(ustawienia["waluty"]))
        nowa_waluta = st.text_input("Nowa waluta")
        if st.button("Dodaj walutę") and nowa_waluta.upper() not in ustawienia["waluty"]:
            ustawienia["waluty"].append(nowa_waluta.upper().strip())
            nadpisz_liste(ws_waluty, ustawienia["waluty"])
            st.rerun()
        st.divider()
        waluta_usun = st.selectbox("Wybierz do usunięcia", ustawienia["waluty"], key="del_waluta")
        if st.button(":material/delete: Usuń walutę") and waluta_usun:
            ustawienia["waluty"].remove(waluta_usun)
            nadpisz_liste(ws_waluty, ustawienia["waluty"])
            st.rerun()

    with col_tickery:
        st.subheader(":material/show_chart: Tickery")
        st.write(", ".join(ustawienia["tickery"]))
        nowy_ticker_ust = st.text_input("Dodaj ticker")
        if st.button("Dodaj ticker") and nowy_ticker_ust.upper() not in ustawienia["tickery"]:
            ustawienia["tickery"].append(nowy_ticker_ust.upper().strip())
            nadpisz_liste(ws_tickery, ustawienia["tickery"])
            st.rerun()
        st.divider()
        ticker_usun = st.selectbox("Wybierz do usunięcia", ustawienia["tickery"], key="del_ticker")
        if st.button(":material/delete: Usuń ticker") and ticker_usun:
            ustawienia["tickery"].remove(ticker_usun)
            nadpisz_liste(ws_tickery, ustawienia["tickery"])
            st.rerun()

# --- ZAKŁADKA 1: DASHBOARD ---
with tab1:
    if not df.empty:
        pozycje = df.groupby(["Portfel", "Ticker", "Nazwa", "Waluta"]).agg({"Ilosc": "sum", "Cena_Zakupu": "mean"}).reset_index()
        pozycje = pozycje[pozycje["Ilosc"] > 0] 
        
        waluty_tickerow = {row['Ticker']: row['Waluta'] for _, row in pozycje.iterrows()}
        srednia_cena = {row['Ticker']: row['Cena_Zakupu'] for _, row in pozycje.iterrows()}
        
        df['Data'] = pd.to_datetime(df['Data'])
        start_date = df['Data'].min().strftime('%Y-%m-%d')
        
        hist_data = pobierz_historie_notowan(df['Ticker'].unique().tolist(), start_date)
        
        if not hist_data.empty:
            dates = pd.date_range(start=start_date, end=pd.Timestamp.today())
            hist_data.index = hist_data.index.tz_localize(None)
            hist_data = hist_data.reindex(dates).ffill().bfill()
            
            wklad_hist, wartosc_hist, sp500_hist, infl_hist = [], [], [], []
            zainwestowano_suma = 0.0
            sp500_shares = 0.0
            infl_kapital = 0.0
            dzienna_stopa_infl = (1 + 0.06) ** (1/365) - 1 
            
            ilosc_aktywow = {t: 0.0 for t in df['Ticker'].unique()}
            
            for d in dates:
                tx_dnia = df[df['Data'] == d]
                for _, tx in tx_dnia.iterrows():
                    w = tx['Waluta']
                    fx = hist_data.loc[d, 'PLN=X'] if 'PLN=X' in hist_data.columns else 4.0
                    if pd.isna(fx): fx = 4.0
                    
                    if w == 'EUR': 
                        fx = hist_data.loc[d, 'EURPLN=X'] if 'EURPLN=X' in hist_data.columns else 4.3
                        if pd.isna(fx): fx = 4.3
                    elif w == 'PLN': 
                        fx = 1.0
                        
                    kwota = tx['Ilosc'] * tx['Cena_Zakupu'] * fx
                    zainwestowano_suma += kwota
                    ilosc_aktywow[tx['Ticker']] += tx['Ilosc']
                    
                    sp500_cena = hist_data.loc[d, '^GSPC'] if '^GSPC' in hist_data.columns else 1.0
                    if pd.isna(sp500_cena) or sp500_cena <= 0: sp500_cena = 1.0
                    
                    sp500_shares += kwota / sp500_cena
                    infl_kapital += kwota
                
                if d != dates[0]:
                    infl_kapital = infl_kapital * (1 + dzienna_stopa_infl)
                
                dzienna_wartosc = 0.0
                for t, ilosc in ilosc_aktywow.items():
                    if ilosc > 0:
                        cena_t = hist_data.loc[d, t] if t in hist_data.columns else np.nan
                        if pd.isna(cena_t): 
                            cena_t = srednia_cena.get(t, 0.0)
                            
                        w = waluty_tickerow.get(t, 'PLN')
                        fx = hist_data.loc[d, 'PLN=X'] if 'PLN=X' in hist_data.columns else 4.0
                        if pd.isna(fx): fx = 4.0
                        
                        if w == 'EUR': 
                            fx = hist_data.loc[d, 'EURPLN=X'] if 'EURPLN=X' in hist_data.columns else 4.3
                            if pd.isna(fx): fx = 4.3
                        elif w == 'PLN': 
                            fx = 1.0
                            
                        dzienna_wartosc += ilosc * cena_t * fx
                        
                wklad_hist.append(zainwestowano_suma)
                wartosc_hist.append(dzienna_wartosc)
                infl_hist.append(infl_kapital)
                
                sp500_curr_price = hist_data.loc[d, '^GSPC'] if '^GSPC' in hist_data.columns else 1.0
                if pd.isna(sp500_curr_price): sp500_curr_price = 1.0
                sp500_hist.append(sp500_shares * sp500_curr_price)
            
            fig_main = go.Figure()
            fig_main.add_trace(go.Scatter(x=dates, y=wartosc_hist, mode='lines', name='Wartość portfela', line=dict(color='#10b981', width=2.5), fill='tozeroy', fillcolor='rgba(16, 185, 129, 0.15)'))
            fig_main.add_trace(go.Scatter(x=dates, y=wklad_hist, mode='lines', name='Wkład własny', line=dict(color='#3b82f6', width=2.5)))
            fig_main.add_trace(go.Scatter(x=dates, y=sp500_hist, mode='lines', name='S&P 500', line=dict(color='#f59e0b', width=1.5, dash='dash')))
            fig_main.add_trace(go.Scatter(x=dates, y=infl_hist, mode='lines', name='Inflacja', line=dict(color='#ef4444', width=1.5, dash='dot')))
            
            if len(dates) > 0:
                fig_main.add_annotation(x=dates[-1], y=wartosc_hist[-1], text=f"{wartosc_hist[-1]:.0f}", showarrow=True, ax=40, ay=-15, bgcolor="#10b981", font=dict(color="white"), arrowcolor="#10b981")
                fig_main.add_annotation(x=dates[-1], y=wklad_hist[-1], text=f"{wklad_hist[-1]:.0f}", showarrow=True, ax=40, ay=15, bgcolor="#3b82f6", font=dict(color="white"), arrowcolor="#3b82f6")

            fig_main.update_layout(title="Wkład i wartość portfela w czasie [PLN]", hovermode="x unified", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), margin=dict(t=50, b=0, l=0, r=40), height=500)
            st.plotly_chart(fig_main, use_container_width=True)
            st.divider()

        if not pozycje.empty:
            for index, row in pozycje.iterrows():
                ticker = row["Ticker"]
                w_akt = row["Waluta"]
                k_wym = kursy.get(w_akt, 1.0)
                aktualna_cena = hist_data[ticker].iloc[-1] if not hist_data.empty and ticker in hist_data.columns else row["Cena_Zakupu"]
                if pd.isna(aktualna_cena): aktualna_cena = row["Cena_Zakupu"]
                
                zainw_oryg = row["Cena_Zakupu"] * row["Ilosc"]
                wart_obecna_oryg = aktualna_cena * row["Ilosc"]
                pozycje.at[index, "Cena zakupu"] = f"{row['Cena_Zakupu']:.2f} {w_akt}"
                pozycje.at[index, "Obecna Cena"] = f"{aktualna_cena:.2f} {w_akt}"
                pozycje.at[index, "Zainwestowano (zł)"] = zainw_oryg * k_wym
                pozycje.at[index, "Wartość (zł)"] = wart_obecna_oryg * k_wym
                pozycje.at[index, "Zysk/Strata (zł)"] = (wart_obecna_oryg * k_wym) - (zainw_oryg * k_wym)
                pozycje.at[index, "ROI (%)"] = ((wart_obecna_oryg - zainw_oryg) / zainw_oryg) * 100 if zainw_oryg > 0 else 0

            calkowita_wartosc = pozycje["Wartość (zł)"].sum()
            calkowicie_zainwestowano = pozycje["Zainwestowano (zł)"].sum()
            calkowity_zysk = pozycje["Zysk/Strata (zł)"].sum()
            calkowite_roi = (calkowity_zysk / calkowicie_zainwestowano) * 100 if calkowicie_zainwestowano > 0 else 0

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Wartość", f"{calkowita_wartosc:,.2f} zł".replace(",", " "))
            m2.metric("Wkład", f"{calkowicie_zainwestowano:,.2f} zł".replace(",", " "))
            m3.metric("Zysk", f"{calkowity_zysk:,.2f} zł".replace(",", " "), f"{calkowity_zysk:,.2f} zł")
            m4.metric("ROI", f"{calkowite_roi:.2f} %", f"{calkowite_roi:.2f} %")
            
            st.divider()

            w1, w2 = st.columns(2)
            with w1:
                fig1 = px.pie(pozycje, values='Wartość (zł)', names='Ticker', hole=0.5, color_discrete_sequence=px.colors.qualitative.Pastel)
                fig1.update_traces(textposition='inside', textinfo='percent+label')
                fig1.update_layout(title="Udział aktywów", margin=dict(t=40, b=0, l=0, r=0), height=300)
                st.plotly_chart(fig1, use_container_width=True)
            with w2:
                wartosc_portfeli = pozycje.groupby("Portfel")["Wartość (zł)"].sum().reset_index()
                fig2 = px.pie(wartosc_portfeli, values='Wartość (zł)', names='Portfel', hole=0.5, color_discrete_sequence=px.colors.qualitative.Pastel)
                fig2.update_traces(textposition='inside', textinfo='percent+label')
                fig2.update_layout(title="Alokacja", margin=dict(t=40, b=0, l=0, r=0), height=300)
                st.plotly_chart(fig2, use_container_width=True)

            st.divider()

            st.subheader("Szczegóły pozycji")
            widok = pozycje[["Portfel", "Ticker", "Nazwa", "Ilosc", "Cena zakupu", "Obecna Cena", "Wartość (zł)", "Zysk/Strata (zł)", "ROI (%)"]].copy()
            st.dataframe(widok.style.format({
                "Ilosc": "{:.4f}", "Wartość (zł)": "{:,.2f} zł", "Zysk/Strata (zł)": "{:,.2f} zł", "ROI (%)": "{:,.2f} %"
            }).map(lambda x: 'color: #10b981' if x > 0 else ('color: #ef4444' if x < 0 else ''), subset=["Zysk/Strata (zł)", "ROI (%)"]), 
            use_container_width=True, hide_index=True)

        else: st.info("Brak otwartych pozycji.")
    else: st.info("Brak danych.")
