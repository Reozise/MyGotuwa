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
        sh = gc.open_by_url("https://docs.google.com/spreadsheets/d/1tvaqcBeB4HKLXwp22GxsFWRthMNFlu3tz6qTLZh-uMc/edit?gid=1463083749#gid=1463083749")
        return sh
    except Exception as e:
        st.error(f"Błąd logowania. Szczegóły: {e}")
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

# --- OCHRONA PRZED BLOKADĄ GOOGLE (CACHE) ---
@st.cache_data(ttl=60, show_spinner="Pobieranie bazy danych z chmury...")
def pobierz_dane_z_chmury():
    return {
        "portfele": pobierz_liste(ws_portfele),
        "waluty": pobierz_liste(ws_waluty),
        "tickery": pobierz_liste(ws_tickery),
        "transakcje": ws_transakcje.get_all_records(numericise_ignore=['all'])
    }

try:
    baza = pobierz_dane_z_chmury()
except Exception as e:
    st.error("Przekroczono limit zapytań do Google. Odczekaj minutę i odśwież stronę.")
    st.stop()

ustawienia = {
    "portfele": list(baza["portfele"]),
    "waluty": list(baza["waluty"]),
    "tickery": list(baza["tickery"])
}
if not ustawienia["portfele"]: ustawienia["portfele"] = ["Główny"]
if not ustawienia["waluty"]: ustawienia["waluty"] = ["PLN"]
if not ustawienia["tickery"]: ustawienia["tickery"] = ["AAPL"]

# --- Funkcja pomocnicza giełdy (threads=False zapobiega padom serwera) ---
@st.cache_data(ttl=3600, show_spinner="Pobieranie danych z giełdy...")
def pobierz_historie_notowan(tickery, start_date):
    if not tickery: return pd.DataFrame()
    symbole = list(set(tickery + ['^GSPC', 'PLN=X', 'EURPLN=X']))
    dane = yf.download(symbole, start=start_date, progress=False, threads=False)
    if isinstance(dane.columns, pd.MultiIndex):
        dane_close = dane['Close']
    else:
        if 'Close' in dane.columns:
            dane_close = pd.DataFrame({symbole[0]: dane['Close']})
        else:
            dane_close = dane
    return dane_close.ffill().bfill()

# --- Pobranie i potężne czyszczenie danych ---
dane_transakcji = baza["transakcje"]
WYMAGANE_KOLUMNY = ["Data", "Portfel", "Ticker", "Nazwa", "Typ", "Ilosc", "Cena_Zakupu", "Waluta"]

if dane_transakcji:
    df = pd.DataFrame(dane_transakcji)
    df.replace("", float("NaN"), inplace=True)
    df.dropna(how='all', inplace=True)
    df.fillna("", inplace=True)
    
    kolumny_tekstowe = ["Data", "Portfel", "Ticker", "Nazwa", "Typ", "Waluta"]
    for kol in kolumny_tekstowe:
        if kol in df.columns:
            df[kol] = df[kol].astype(str).str.strip()
            
    if 'Ilosc' in df.columns:
        df['Ilosc'] = pd.to_numeric(df['Ilosc'].astype(str).str.replace(',', '.').str.replace(' ', ''), errors='coerce').fillna(0.0)
    if 'Cena_Zakupu' in df.columns:
        df['Cena_Zakupu'] = pd.to_numeric(df['Cena_Zakupu'].astype(str).str.replace(',', '.').str.replace(' ', ''), errors='coerce').fillna(0.0)
        
    df = df[df["Ticker"] != ""]

    # AUTO-SYNCHRONIZACJA
    wymaga_zapisania = False
    nowe_tickery = [t for t in df["Ticker"].unique() if t not in ustawienia["tickery"]]
    if nowe_tickery:
        ustawienia["tickery"].extend(nowe_tickery)
        nadpisz_liste(ws_tickery, ustawienia["tickery"])
        wymaga_zapisania = True
        
    nowe_portfele = [p for p in df["Portfel"].unique() if p not in ustawienia["portfele"]]
    if nowe_portfele:
        ustawienia["portfele"].extend(nowe_portfele)
        nadpisz_liste(ws_portfele, ustawienia["portfele"])
        wymaga_zapisania = True
        
    nowe_waluty = [w for w in df["Waluta"].unique() if w not in ustawienia["waluty"]]
    if nowe_waluty:
        ustawienia["waluty"].extend(nowe_waluty)
        nadpisz_liste(ws_waluty, ustawienia["waluty"])
        wymaga_zapisania = True

    if wymaga_zapisania:
        st.cache_data.clear()

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
else: st.sidebar.success(":material/wifi: Kursy na żywo")
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
    
    # Dynamiczny layout bez st.form - reaguje na wybory na bieżąco
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        data_operacji = st.date_input("Data operacji")
        portfel = st.selectbox("Wybierz portfel", ustawienia["portfele"])
        
    with col2:
        opcje_tickerow = ["➕ Dodaj nowy..."] + ustawienia["tickery"]
        wybrany_ticker = st.selectbox("Wybierz Ticker", opcje_tickerow)
        
        # Pojawia się tylko wtedy, gdy dodajemy nową spółkę
        if wybrany_ticker == "➕ Dodaj nowy...":
            docelowy_ticker = st.text_input("Nowy symbol (np. AAPL)").upper().strip()
            docelowa_nazwa = st.text_input("Nazwa spółki").strip()
        else:
            docelowy_ticker = wybrany_ticker
            # Aplikacja sprawdza w historii, jak nazywa się ten Ticker, i nie pyta o to po raz drugi
            znane_nazwy = [str(n).strip() for n in df[df["Ticker"] == docelowy_ticker]["Nazwa"].unique() if str(n).strip()]
            if znane_nazwy:
                docelowa_nazwa = znane_nazwy[0]
                st.info(f"🏷️ {docelowa_nazwa}")
            else:
                docelowa_nazwa = st.text_input("Podaj nazwę dla tego tickera").strip()
                
    with col3:
        typ = st.selectbox("Typ operacji", ["KUPNO", "SPRZEDAŻ"])
        waluta = st.selectbox("Waluta transakcji", ustawienia["waluty"])
        
    with col4:
        ilosc = st.number_input("Ilość", min_value=0.00001, format="%g")
        cena = st.number_input("Cena za sztukę", min_value=0.01, format="%g")
        st.write("") 
        zapisz = st.button("💾 Zapisz do portfela", type="primary", use_container_width=True)

    if zapisz:
        if docelowy_ticker == "" or docelowa_nazwa == "":
            st.error("Podaj poprawny ticker i nazwę!")
        else:
            if docelowy_ticker not in ustawienia["tickery"]:
                ustawienia["tickery"].append(docelowy_ticker)
                nadpisz_liste(ws_tickery, ustawienia["tickery"])
            
            ws_transakcje.append_row([
                data_operacji.strftime("%Y-%m-%d"), 
                portfel, 
                docelowy_ticker, 
                docelowa_nazwa, 
                typ, 
                float(ilosc if typ == "KUPNO" else -ilosc), 
                float(cena), 
                waluta
            ], value_input_option='USER_ENTERED')
            st.success(f"Dodano {typ} dla {docelowy_ticker} w chmurze!")
            st.cache_data.clear() 
            st.rerun()

# --- ZAKŁADKA 3: HISTORIA ---
with tab3:
    st.header("Pełna historia operacji")
    if not df.empty:
        df_historia = df.sort_values(by="Data", ascending=False).reset_index(drop=True)
        st.dataframe(df_historia.astype(str), width='stretch')
        st.info("Aby usunąć lub zedytować starszą transakcję, otwórz bezpośrednio swój arkusz Google Sheets. Jest to najbezpieczniejsze dla integralności bazy danych.")
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
            st.cache_data.clear()
            st.rerun()
        st.divider()
        portfel_usun = st.selectbox("Wybierz do usunięcia", ustawienia["portfele"], key="del_portfel")
        if st.button(":material/delete: Usuń portfel") and portfel_usun:
            ustawienia["portfele"].remove(portfel_usun)
            nadpisz_liste(ws_portfele, ustawienia["portfele"])
            st.cache_data.clear()
            st.rerun()

    with col_waluty:
        st.subheader(":material/payments: Waluty")
        st.write(", ".join(ustawienia["waluty"]))
        nowa_waluta = st.text_input("Nowa waluta")
        if st.button("Dodaj walutę") and nowa_waluta.upper() not in ustawienia["waluty"]:
            ustawienia["waluty"].append(nowa_waluta.upper().strip())
            nadpisz_liste(ws_waluty, ustawienia["waluty"])
            st.cache_data.clear()
            st.rerun()
        st.divider()
        waluta_usun = st.selectbox("Wybierz do usunięcia", ustawienia["waluty"], key="del_waluta")
        if st.button(":material/delete: Usuń walutę") and waluta_usun:
            ustawienia["waluty"].remove(waluta_usun)
            nadpisz_liste(ws_waluty, ustawienia["waluty"])
            st.cache_data.clear()
            st.rerun()

    with col_tickery:
        st.subheader(":material/show_chart: Tickery")
        st.write(", ".join(ustawienia["tickery"]))
        nowy_ticker_ust = st.text_input("Dodaj ticker")
        if st.button("Dodaj ticker") and nowy_ticker_ust.upper() not in ustawienia["tickery"]:
            ustawienia["tickery"].append(nowy_ticker_ust.upper().strip())
            nadpisz_liste(ws_tickery, ustawienia["tickery"])
            st.cache_data.clear()
            st.rerun()
        st.divider()
        ticker_usun = st.selectbox("Wybierz do usunięcia", ustawienia["tickery"], key="del_ticker")
        if st.button(":material/delete: Usuń ticker") and ticker_usun:
            ustawienia["tickery"].remove(ticker_usun)
            nadpisz_liste(ws_tickery, ustawienia["tickery"])
            st.cache_data.clear()
            st.rerun()

# --- ZAKŁADKA 1: DASHBOARD ---
with tab1:
    if not df.empty:
        st.markdown("### Filtry")
        
        col_f1, col_f2 = st.columns(2)
        
        with col_f1:
            lista_portfeli = sorted(df["Portfel"].unique().tolist())
            wybrane_portfele = st.multiselect(
                "Wybierz portfele do wyświetlenia:", 
                options=lista_portfeli, 
                default=lista_portfeli
            )
            
        with col_f2:
            df_temp = df[df["Portfel"].isin(wybrane_portfele)] if wybrane_portfele else df
            lista_aktywow = sorted(df_temp["Nazwa"].unique().tolist())
            wybrane_aktywa = st.multiselect(
                "Wybierz aktywa do wyświetlenia:", 
                options=lista_aktywow, 
                default=lista_aktywow
            )
            
        st.divider()

        df_filtered = df[
            (df["Portfel"].isin(wybrane_portfele)) & 
            (df["Nazwa"].isin(wybrane_aktywa))
        ].copy()

        if not df_filtered.empty:
            df_filtered['Wartosc_Zakupu'] = df_filtered['Ilosc'] * df_filtered['Cena_Zakupu']
            pozycje = df_filtered.groupby(["Portfel", "Ticker", "Nazwa", "Waluta"]).agg({"Ilosc": "sum", "Wartosc_Zakupu": "sum"}).reset_index()
            pozycje['Cena_Zakupu'] = pozycje['Wartosc_Zakupu'] / pozycje['Ilosc']
            pozycje = pozycje[pozycje["Ilosc"] > 0] 
            
            waluty_tickerow = {row['Ticker']: row['Waluta'] for _, row in pozycje.iterrows()}
            srednia_cena = {row['Ticker']: row['Cena_Zakupu'] for _, row in pozycje.iterrows()}
            
            df_filtered['Data'] = pd.to_datetime(df_filtered['Data'])
            start_date = df_filtered['Data'].min().strftime('%Y-%m-%d')
            
            hist_data = pobierz_historie_notowan(df_filtered['Ticker'].unique().tolist(), start_date)
            
            if not hist_data.empty:
                dates = pd.date_range(start=start_date, end=pd.Timestamp.today())
                hist_data.index = hist_data.index.tz_localize(None)
                hist_data = hist_data.reindex(dates).ffill().bfill()
                
                wklad_hist, wartosc_hist, sp500_hist, infl_hist = [], [], [], []
                zainwestowano_suma = 0.0
                sp500_shares = 0.0
                infl_kapital = 0.0
                dzienna_stopa_infl = (1 + 0.06) ** (1/365) - 1 
                
                ilosc_aktywow = {t: 0.0 for t in df_filtered['Ticker'].unique()}
                
                for d in dates:
                    tx_dnia = df_filtered[df_filtered['Data'] == d]
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

                fig_main.update_layout(title="Wkład i wartość wybranych portfeli w czasie [PLN]", hovermode="x unified", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), margin=dict(t=50, b=0, l=0, r=40), height=500)
                st.plotly_chart(fig_main, width='stretch')
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
                    
                    cz_czysta = f"{row['Cena_Zakupu']:.6f}".rstrip('0').rstrip('.')
                    oc_czysta = f"{aktualna_cena:.6f}".rstrip('0').rstrip('.')
                    
                    pozycje.at[index, "Cena zakupu"] = f"{cz_czysta} {w_akt}"
                    pozycje.at[index, "Obecna Cena"] = f"{oc_czysta} {w_akt}"
                    pozycje.at[index, "Zainwestowano (zł)"] = zainw_oryg * k_wym
                    pozycje.at[index, "Wartość (zł)"] = wart_obecna_oryg * k_wym
                    pozycje.at[index, "Zysk/Strata (zł)"] = (wart_obecna_oryg * k_wym) - (zainw_oryg * k_wym)
                    pozycje.at[index, "ROI (%)"] = ((wart_obecna_oryg - zainw_oryg) / zainw_oryg) * 100 if zainw_oryg > 0 else 0

                try:
                    calkowita_wartosc = wartosc_hist[-1]
                    calkowicie_zainwestowano = wklad_hist[-1]
                except Exception:
                    calkowita_wartosc = pozycje["Wartość (zł)"].sum()
                    calkowicie_zainwestowano = pozycje["Zainwestowano (zł)"].sum()

                calkowity_zysk = calkowita_wartosc - calkowicie_zainwestowano
                calkowite_roi = (calkowity_zysk / calkowicie_zainwestowano) * 100 if calkowicie_zainwestowano > 0 else 0

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Wartość", f"{calkowita_wartosc:,.2f} zł".replace(",", " "))
                m2.metric("Wkład", f"{calkowicie_zainwestowano:,.2f} zł".replace(",", " "))
                m3.metric("Zysk", f"{calkowity_zysk:,.2f} zł".replace(",", " "), f"{calkowity_zysk:,.2f} zł")
                m4.metric("ROI", f"{calkowite_roi:.2f} %", f"{calkowite_roi:.2f} %")
                
                st.divider()

                w1, w2 = st.columns(2)
                with w1:
                    fig1 = px.pie(pozycje, values='Wartość (zł)', names='Nazwa', hole=0.5, color_discrete_sequence=px.colors.qualitative.Pastel)
                    fig1.update_traces(textposition='inside', textinfo='percent+label')
                    fig1.update_layout(title="Udział aktywów", margin=dict(t=40, b=0, l=0, r=0), height=300)
                    st.plotly_chart(fig1, width='stretch')
                with w2:
                    wartosc_portfeli = pozycje.groupby("Portfel")["Wartość (zł)"].sum().reset_index()
                    fig2 = px.pie(wartosc_portfeli, values='Wartość (zł)', names='Portfel', hole=0.5, color_discrete_sequence=px.colors.qualitative.Pastel)
                    fig2.update_traces(textposition='inside', textinfo='percent+label')
                    fig2.update_layout(title="Alokacja", margin=dict(t=40, b=0, l=0, r=0), height=300)
                    st.plotly_chart(fig2, width='stretch')

                st.divider()

                st.subheader("Szczegóły pozycji")
                widok = pozycje[["Portfel", "Ticker", "Nazwa", "Ilosc", "Cena zakupu", "Obecna Cena", "Wartość (zł)", "Zysk/Strata (zł)", "ROI (%)"]].copy()
                
                # Usunięcie zer z Ilości w tabeli
                widok["Ilosc"] = widok["Ilosc"].apply(lambda x: f"{x:.6f}".rstrip('0').rstrip('.'))
                widok["Wartość (zł)"] = widok["Wartość (zł)"].apply(lambda x: f"{x:,.2f} zł".replace(",", " "))
                widok["Zysk/Strata (zł)"] = widok["Zysk/Strata (zł)"].apply(lambda x: f"{x:,.2f} zł".replace(",", " "))
                widok["ROI (%)"] = widok["ROI (%)"].apply(lambda x: f"{x:.2f} %")
                
                st.dataframe(widok, width='stretch', hide_index=True)

            else:
                st.info("Brak otwartych pozycji dla wybranych kryteriów.")
        else:
            st.info("Wybierz przynajmniej jeden portfel i jedno aktywo z filtrów powyżej, aby zobaczyć statystyki.")
    else:
        st.info("Brak danych transakcyjnych.")
