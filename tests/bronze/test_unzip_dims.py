from src.bronze.unzip_dims import read_dim_csv


def test_read_dim_csv_trims_codes_and_decodes_latin1() -> None:
    # latin-1 bytes, ';'-separated, trailing-space codes, accented name.
    raw = "coramo;noramo\n0776      ;0776 - Caução  \n0111;Vida\n".encode("latin-1")
    df = read_dim_csv(raw)

    assert df.columns == ["coramo", "noramo"]
    rows = df.to_dicts()
    assert rows[0] == {"coramo": "0776", "noramo": "0776 - Caução"}
    assert rows[1] == {"coramo": "0111", "noramo": "Vida"}


def test_read_dim_csv_tolerates_stray_quotes() -> None:
    # Company names with stray double-quotes must not break parsing.
    raw = 'Coenti;Noenti\n04740     ;ACME "BIG" SEGUROS S.A.\n'.encode("latin-1")
    df = read_dim_csv(raw)

    rows = df.to_dicts()
    assert rows[0]["Coenti"] == "04740"
    assert rows[0]["Noenti"] == 'ACME "BIG" SEGUROS S.A.'
