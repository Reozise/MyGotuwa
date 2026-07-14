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
            # Właściwa średnia ważona dla poprawnych wyników
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
                    pozycje.at[index, "Cena zakupu"] = f"{row['Cena_Zakupu']:.2f} {w_akt}"
                    pozycje.at[index, "Obecna Cena"] = f"{aktualna_cena:.2f} {w_akt}"
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
                    # Wykres z nazwą spółki zamiast tickera
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
                
                # Zabezpieczenie przed PyArrow Crash
                widok["Ilosc"] = widok["Ilosc"].apply(lambda x: f"{x:.4f}")
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
