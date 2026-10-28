# GeoTrabalho - Espacializador RAIS/CAGED (DardoWeb)

**Autor / Author:** Luís Eduardo Araújo de Souza (`luisaraujodesouza.geo@gmail.com`)  
**Repositório / Repository:** [https://github.com/duduluiss/geotrabalho-qgis](https://github.com/duduluiss/geotrabalho-qgis)  
**Compatibilidade / Compatibility:** QGIS 3.28+ & QGIS 4.x (`PyQt5` / `PyQt6`, `supportsQt6=True`)  
**Licença / License:** GNU GPL v2+ / v3  
**Versão / Version:** 1.2.0  

---

## 🇧🇷 Descrição (Português)

O **GeoTrabalho - Espacializador RAIS/CAGED** é um complemento para o QGIS projetado para conectar, consultar e espacializar automaticamente dados de emprego formal, empresas e dinâmica econômica do Ministério do Trabalho e Emprego (MTE) via **DardoWeb (bi.trabalho.gov.br)**.

### Principais Recursos (v1.2.0)
1. **Conexão e Consulta Online Automática**:
   - Conecta-se diretamente ao DardoWeb com usuário e senha públicos (`basico` / `12345678`) ou credenciais próprias.
   - Permite consultar **RAIS Vínculos** (trabalhadores, salários, escolaridade), **RAIS Estabelecimentos** (empresas ativas, porte, distribuição territorial) e **CAGED** (fluxo mensal de contratações, demissões e saldo).
2. **Suporte Completo ao Ano 2025 e Roteamento Histórico até 2002**:
   - Suporte nativo ao ano corrente de 2025, 2024, 2023, 2022.
   - Roteamento transparente para cubos de séries históricas (2002 a 2021) sem erros de conexão.
   - Compatibilização automática para anos $\le 2005$ (comutação inteligente de CNAE 2.0 para **CNAE 95** e de Escolaridade para **Grau de Instrução 1985-2005**).
3. **Cruzamentos Multidimensionais (Sexo Trabalhador, Porte, Faixa Etária, etc. filtrados por CNAE)**:
   - Permite combinar qualquer dimensão demográfica ou cadastral (ex: **Sexo Trabalhador - Homens vs Mulheres**, **Tamanho do Estabelecimento - Porte**, etc.) com filtros setoriais específicos.
   - Injeta automaticamente parâmetros nativos de seleção (`YZ`/`YC`) no servidor do DardoWeb, obtendo a distribuição exata de homens e mulheres por município naquela atividade (ex: *Pecuária*, *Produção de Laticínios*, *Calçados*).
4. **Catálogo Completo da CNAE (Seções, Divisões, Grupos e Classes)**:
   - Catálogo integrado com 21 seções, 87 divisões, 285 grupos e 673 classes e seus respectivos códigos oficiais do IBGE.
   - Menu com busca textual e autocompletar em tempo real.
   - Cálculo automático de Total Consolidado da Atividade Filtrada (`VINC_FILTR`) e Percentual sobre a Economia Municipal (`PCT_FILTR`).
5. **Preservação Contínua da Malha Municipal (Sem 'Buracos')**:
   - 100% dos polígonos municipais do estado são preservados na camada final. Municípios sem vínculos ou ausentes na consulta recebem 0 vagas, garantindo mapas coropléticos contínuos e sem falhas espaciais.
6. **Resolução de Geocódigos para o IBGE (7 dígitos)**:
   - Traduz automaticamente os nomes e códigos mistos do DardoWeb para o código oficial do IBGE de 7 dígitos para todos os 5.571 municípios brasileiros, incluindo nomes com hífens e apóstrofos (ex: *Grão-Pará*, *Herval d'Oeste*, *Santiago do Sul*).
7. **Download Automático da Malha Municipal**:
   - Baixa e armazena em cache as geometrias oficiais de qualquer UF ou do Brasil inteiro pela API de Malhas v3 do IBGE.
8. **Simbologias Temáticas Inteligentes**:
   - **Gênero / Predominância**: destaque automático para predominância masculina (azul) ou feminina (rosa/magenta).
   - **Predominância Setorial CNAE**: colore cada município pelo setor econômico líder com cores econômicas padronizadas.
   - **Saldo Bipolar do CAGED**: mapa divergente centrado no zero (Vermelho para perda de vagas, Branco/Neutro para estabilidade, Azul para geração de empregos).
   - **Graduado por Quantis / Atividade Filtrada**: mapas coropléticos de volume de empregos na atividade selecionada.
9. **Interface Responsiva**:
   - Janela otimizada com largura estendida ($920\text{px}$) e proporções calibradas para visualização confortável de todos os campos sem rolagem lateral.
10. **Importação de Arquivos Locais**:
   - Suporte a tabelas salvas manualmente em formato HTML pelo DardoWeb.

---

## 🌐 Overview (English — For QGIS Plugin Reviewers)

**GeoTrabalho - Espacializador RAIS/CAGED (DardoWeb)** is a QGIS 3 & QGIS 4 (`supportsQt6=True`) plugin for spatializing official labor market and firm microdata from Brazil's Ministry of Labor (MTE - RAIS / CAGED / DardoWeb).

- Connects directly to the online OLAP engine (`bi.trabalho.gov.br`) using public or custom credentials.
- Full support for 2025 current data and historical cube routing back to 2002 with automatic classification back-porting (CNAE 95 and historical schooling grades).
- Multi-dimensional cross-tabulation: filter demographic dimensions (such as Worker Gender / Establishment Size) by specific economic activities (Livestock, Footwear, Dairy, etc.) via native OLAP server injection.
- Complete built-in catalog of 21 sections, 87 divisions, 285 groups, and 673 classes with official IBGE codes.
- Zero-gap mesh preservation: retains all municipal polygons, filling empty/unreported areas with 0 to prevent holes.
- Automates geocoding to 7-digit IBGE municipal codes for all 5,571 municipalities.
- Automatically downloads official municipal vector geometries via IBGE v3 Mesh API.
- Applies specialized labor market cartography (gender predominance, activity choropleths, sector dominance, bipolar employment net flows).
