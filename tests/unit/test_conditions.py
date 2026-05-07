"""Unit tests for condition parsing — ≥15 cases covering all edge cases from §D."""

from watari_core.conditions import (
    Condition,
    GradeCompany,
    parse_cardrush_condition,
    parse_grade_company_score,
    parse_snkrdunk_condition,
)


class TestCardrushCondition:
    """Cardrush product name → (Condition, is_graded) parsing."""

    def test_no_bracket_defaults_to_raw_a(self):
        cond, graded = parse_cardrush_condition("ポケモンカード リザードンex SAR")
        assert cond == Condition.A
        assert graded is False

    def test_condition_a(self):
        cond, graded = parse_cardrush_condition("リザードンex 〔状態A〕")
        assert cond == Condition.A
        assert graded is False

    def test_condition_a_minus(self):
        cond, graded = parse_cardrush_condition("リザードンex 〔状態A-〕")
        assert cond == Condition.A_MINUS
        assert graded is False

    def test_condition_b(self):
        cond, graded = parse_cardrush_condition("リザードンex 〔状態B〕")
        assert cond == Condition.B
        assert graded is False

    def test_condition_b_plus_maps_to_b(self):
        cond, graded = parse_cardrush_condition("リザードンex 〔状態B+〕")
        assert cond == Condition.B
        assert graded is False

    def test_condition_b_minus_maps_to_b(self):
        cond, graded = parse_cardrush_condition("リザードンex 〔状態B-〕")
        assert cond == Condition.B
        assert graded is False

    def test_condition_c(self):
        cond, graded = parse_cardrush_condition("リザードンex 〔状態C〕")
        assert cond == Condition.C
        assert graded is False

    def test_condition_c_plus_maps_to_c(self):
        cond, graded = parse_cardrush_condition("リザードンex 〔状態C+〕")
        assert cond == Condition.C
        assert graded is False

    def test_condition_c_minus_maps_to_c(self):
        cond, graded = parse_cardrush_condition("リザードンex 〔状態C-〕")
        assert cond == Condition.C
        assert graded is False

    def test_psa_graded_detected(self):
        cond, graded = parse_cardrush_condition("リザードンex 【PSA10】")
        assert cond is None
        assert graded is True

    def test_bgs_graded_detected(self):
        cond, graded = parse_cardrush_condition("リザードンex 【BGS9】")
        assert cond is None
        assert graded is True

    def test_cgc_graded_detected(self):
        cond, graded = parse_cardrush_condition("リザードンex 【CGC8】")
        assert cond is None
        assert graded is True

    def test_sgc_graded_detected(self):
        cond, graded = parse_cardrush_condition("リザードンex 【SGC10】")
        assert cond is None
        assert graded is True

    def test_graded_plus_condition_bracket_graded_wins(self):
        """When both graded and condition bracket present, graded takes priority."""
        cond, graded = parse_cardrush_condition("リザードンex 【PSA10】 〔状態A-〕")
        assert cond is None
        assert graded is True

    def test_ar_rarity_tag_not_graded(self):
        """【AR】is a rarity tag, not a grading label — should default to A."""
        cond, graded = parse_cardrush_condition("ピカチュウ 【AR】")
        assert cond == Condition.A
        assert graded is False

    def test_sir_rarity_tag_not_graded(self):
        """【SIR】is a rarity tag, not a grading label."""
        cond, graded = parse_cardrush_condition("リザードンex 【SIR】")
        assert cond == Condition.A
        assert graded is False

    def test_unknown_condition_bracket_returns_none(self):
        """Unknown condition inside brackets returns None."""
        cond, graded = parse_cardrush_condition("リザードンex 〔状態Z〕")
        assert cond is None
        assert graded is False


class TestParseGradeCompanyScore:
    """parse_grade_company_score: valid grades, invalid input, edge cases."""

    def test_psa10(self):
        result = parse_grade_company_score("PSA10")
        assert result is not None
        company, score = result
        assert company == GradeCompany.PSA
        assert score == 10.0

    def test_bgs95(self):
        result = parse_grade_company_score("BGS9.5")
        assert result is not None
        company, score = result
        assert company == GradeCompany.BGS
        assert score == 9.5

    def test_cgc10(self):
        result = parse_grade_company_score("CGC10")
        assert result is not None
        company, score = result
        assert company == GradeCompany.CGC
        assert score == 10.0

    def test_psa9(self):
        result = parse_grade_company_score("PSA9")
        assert result is not None
        assert result[1] == 9.0

    def test_case_insensitive(self):
        result = parse_grade_company_score("psa10")
        assert result is not None
        assert result[0] == GradeCompany.PSA

    def test_whitespace_stripped(self):
        result = parse_grade_company_score("  PSA10  ")
        assert result is not None
        assert result[0] == GradeCompany.PSA
        assert result[1] == 10.0

    def test_sgc_returns_none(self):
        """SGC is deferred — not in GradeCompany."""
        assert parse_grade_company_score("SGC10") is None

    def test_unknown_company_returns_none(self):
        assert parse_grade_company_score("XYZ10") is None

    def test_no_score_returns_none(self):
        assert parse_grade_company_score("PSA") is None

    def test_empty_returns_none(self):
        assert parse_grade_company_score("") is None

    def test_only_digits_returns_none(self):
        assert parse_grade_company_score("10") is None

    def test_bgs_decimal_score(self):
        result = parse_grade_company_score("BGS8.5")
        assert result is not None
        assert result[1] == 8.5


class TestSnkrdunkCondition:
    """SNKRDUNK API condition string → Condition mapping."""

    def test_s_maps_to_a(self):
        assert parse_snkrdunk_condition("S") == Condition.A

    def test_a_maps_to_a(self):
        assert parse_snkrdunk_condition("A") == Condition.A

    def test_b_maps_to_b(self):
        assert parse_snkrdunk_condition("B") == Condition.B

    def test_c_maps_to_c(self):
        assert parse_snkrdunk_condition("C") == Condition.C

    def test_lowercase_s(self):
        assert parse_snkrdunk_condition("s") == Condition.A

    def test_lowercase_a(self):
        assert parse_snkrdunk_condition("a") == Condition.A

    def test_lowercase_b(self):
        assert parse_snkrdunk_condition("b") == Condition.B

    def test_lowercase_c(self):
        assert parse_snkrdunk_condition("c") == Condition.C

    def test_whitespace_handling(self):
        assert parse_snkrdunk_condition("  A  ") == Condition.A

    def test_whitespace_with_lowercase(self):
        assert parse_snkrdunk_condition(" b ") == Condition.B

    def test_unknown_returns_none(self):
        assert parse_snkrdunk_condition("D") is None

    def test_empty_string_returns_none(self):
        assert parse_snkrdunk_condition("") is None

    def test_unknown_word_returns_none(self):
        assert parse_snkrdunk_condition("mint") is None
