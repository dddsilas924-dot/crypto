"""テスト: commentary.py + veto.py + alert.py新フォーマット"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_commentary():
    """Task 4: Commentary テンプレートベースコメンタリー"""
    print("\n=== Test: Commentary ===")
    from src.core.commentary import Commentary
    passed = 0
    total = 0

    # Regime comment
    total += 1
    comment = Commentary.regime_comment('B', 35, 2.5)
    assert 'アルト祭り' in comment, f"Expected 'アルト祭り' in: {comment}"
    assert 'Fear域' in comment or 'Bot-Surge' in comment
    print(f"  ✅ regime_comment Pattern B: {comment[:60]}...")
    passed += 1

    total += 1
    comment = Commentary.regime_comment('C', 20, -5.0)
    assert '全面安' in comment
    assert 'BTC急落' in comment
    print(f"  ✅ regime_comment Pattern C + BTC急落")
    passed += 1

    # Fear comment
    total += 1
    fc = Commentary._fear_comment(5)
    assert '極限恐怖' in fc
    assert 'Bot-Alpha' in fc
    print(f"  ✅ fear_comment fg=5: {fc[:50]}...")
    passed += 1

    total += 1
    fc = Commentary._fear_comment(85)
    assert '極限貪欲' in fc
    print(f"  ✅ fear_comment fg=85: {fc[:50]}...")
    passed += 1

    # Bot status
    total += 1
    bs = Commentary.bot_status_comment('alpha', 'fired')
    assert '発火' in bs
    print(f"  ✅ bot_status alpha fired: {bs[:50]}...")
    passed += 1

    total += 1
    bs = Commentary.bot_status_comment('surge', 'waiting')
    assert '待機' in bs
    print(f"  ✅ bot_status surge waiting")
    passed += 1

    # Tier1 summary
    total += 1
    t1 = Commentary.tier1_summary(180, 870, {'DeFi': 40, 'AI': 30, 'L1': 25})
    assert '180/870' in t1
    assert 'DeFi' in t1
    print(f"  ✅ tier1_summary: {t1[:60]}...")
    passed += 1

    # Tier2 symbol comment
    total += 1
    t2 = Commentary.tier2_symbol_comment(
        'SOL/USDT:USDT', 45.0, 25.0,
        {'L02': {'score': 20}, 'L03': {'score': 15}, 'L09': {'score': 10}, 'L17': {}, 'L_alpha': {}},
        {'L08': {'score': 20}, 'L10': {'score': 15}, 'L13': {'score': -5}},
        is_new_listing=True,
    )
    assert 'SOL' in t2
    assert '70pt' in t2
    assert 'T1:45' in t2
    assert 'T2:25' in t2
    assert '🆕' in t2
    print(f"  ✅ tier2_symbol_comment: {t2[:60]}...")
    passed += 1

    # Trigger comment (enhanced with market meaning)
    total += 1
    tc = Commentary.trigger_comment('BTC 1h +6.2%')
    assert '市場意味' in tc
    assert 'フラッシュ' in tc
    assert '監視' in tc
    print(f"  ✅ trigger_comment BTC 1h: {tc[:60]}...")
    passed += 1

    # Score guide (with thresholds)
    total += 1
    sg = Commentary.score_guide_footer()
    assert 'max130' in sg
    assert 'VETO=-100' in sg
    assert '90+' in sg  # New threshold guide
    print(f"  ✅ score_guide_footer")
    passed += 1

    # Build report commentary
    total += 1
    rc = Commentary.build_report_commentary({
        'regime': 'B', 'fear_greed': 35, 'btc_change_24h': 1.5,
        'tier1_passed': [None] * 150, 'tier2_passed': [None] * 60,
    })
    assert '結論' in rc
    assert 'アルト祭り' in rc
    print(f"  ✅ build_report_commentary")
    passed += 1

    # Conclusion
    total += 1
    c = Commentary._build_conclusion('C', 30, 100)
    assert '全面安' in c
    print(f"  ✅ _build_conclusion Pattern C")
    passed += 1

    total += 1
    c = Commentary._build_conclusion('F', 5, 100)
    assert '極限恐怖' in c
    print(f"  ✅ _build_conclusion Fear=5")
    passed += 1

    print(f"\n  Commentary: {passed}/{total} passed")
    return passed, total


def test_veto():
    """Task 5: VetoSystem 3層VETO"""
    print("\n=== Test: VetoSystem ===")
    from src.core.veto import VetoSystem
    passed = 0
    total = 0

    # 基本初期化
    total += 1
    v = VetoSystem({'veto': {'manual_symbols': ['SCAM/USDT:USDT'], 'min_price': 0.0}})
    assert len(v.manual_symbols) == 1
    print(f"  ✅ VetoSystem init with manual_symbols")
    passed += 1

    # Layer 3: 手動VETO
    total += 1
    vetoed, reason = v.check('SCAM/USDT:USDT', price=1.0, volume_usd=1000)
    assert vetoed is True
    assert '手動VETO' in reason
    print(f"  ✅ Layer 3 manual veto: {reason[:50]}")
    passed += 1

    # Layer 2: 価格0
    total += 1
    vetoed, reason = v.check('TEST/USDT:USDT', price=0, volume_usd=1000)
    assert vetoed is True
    assert '価格' in reason
    print(f"  ✅ Layer 2 price=0 veto")
    passed += 1

    # Layer 2: 負の価格
    total += 1
    vetoed, reason = v.check('TEST/USDT:USDT', price=-1.0, volume_usd=1000)
    assert vetoed is True
    print(f"  ✅ Layer 2 negative price veto")
    passed += 1

    # Layer 2: OHLCVデータ欠損
    total += 1
    vetoed, reason = v.check('TEST/USDT:USDT', price=1.0, volume_usd=1000, ohlcv_available=False)
    assert vetoed is True
    assert 'OHLCV' in reason
    print(f"  ✅ Layer 2 OHLCV missing veto")
    passed += 1

    # Layer 2: スプレッド過大
    total += 1
    v2 = VetoSystem({'veto': {'max_spread_pct': 5.0}})
    vetoed, reason = v2.check('TEST/USDT:USDT', price=1.0, volume_usd=1000, spread_pct=8.0)
    assert vetoed is True
    assert 'スプレッド' in reason
    print(f"  ✅ Layer 2 spread veto")
    passed += 1

    # 正常通過
    total += 1
    vetoed, reason = v.check('GOOD/USDT:USDT', price=50.0, volume_usd=100000)
    assert vetoed is False
    assert reason is None
    print(f"  ✅ Normal pass (no veto)")
    passed += 1

    # 手動VETO追加/削除
    total += 1
    v.add_manual_veto('NEW/USDT:USDT')
    assert v.is_manual_vetoed('NEW/USDT:USDT')
    v.remove_manual_veto('NEW/USDT:USDT')
    assert not v.is_manual_vetoed('NEW/USDT:USDT')
    print(f"  ✅ add/remove manual veto")
    passed += 1

    # VETO統計
    total += 1
    stats = v.get_veto_stats()
    assert stats['total'] > 0
    assert stats['manual_count'] == 1
    print(f"  ✅ veto_stats: {stats}")
    passed += 1

    # VETO履歴
    total += 1
    recent = v.get_recent_vetos(limit=5)
    assert len(recent) > 0
    assert 'symbol' in recent[0]
    print(f"  ✅ recent_vetos: {len(recent)} entries")
    passed += 1

    # extra_checks
    total += 1
    vetoed, reason = v.check('TEST/USDT:USDT', price=1.0, volume_usd=1000,
                              extra_checks={'Liquidity': (50000, 100000, 'lt')})
    assert vetoed is True
    assert 'Liquidity' in reason
    print(f"  ✅ extra_checks lt veto")
    passed += 1

    # デフォルト config
    total += 1
    v3 = VetoSystem()
    vetoed, reason = v3.check('TEST/USDT:USDT', price=1.0, volume_usd=1000)
    assert vetoed is False
    print(f"  ✅ Default config - no veto")
    passed += 1

    print(f"\n  VetoSystem: {passed}/{total} passed")
    return passed, total


def test_alert_imports():
    """Task 2: alert.py が正しくimportできるか"""
    print("\n=== Test: Alert imports ===")
    passed = 0
    total = 0

    total += 1
    try:
        from src.execution.alert import TelegramAlert
        assert hasattr(TelegramAlert, 'send_market_report')
        assert hasattr(TelegramAlert, 'send_community_report')
        assert hasattr(TelegramAlert, '_build_market_premise')
        assert hasattr(TelegramAlert, '_build_bot_status_section')
        assert hasattr(TelegramAlert, '_build_tier2_section')
        assert hasattr(TelegramAlert, '_score_breakdown')
        assert hasattr(TelegramAlert, '_matching_bots')
        assert hasattr(TelegramAlert, '_bot_status_line')
        print(f"  ✅ TelegramAlert new methods exist")
        passed += 1
    except Exception as e:
        print(f"  ❌ Import failed: {e}")

    total += 1
    try:
        from src.core.engine import EmpireMonitor
        print(f"  ✅ EmpireMonitor imports VetoSystem")
        passed += 1
    except Exception as e:
        print(f"  ❌ Engine import failed: {e}")

    print(f"\n  Alert imports: {passed}/{total} passed")
    return passed, total


def test_enhanced_features():
    """Enhanced features: bot status distance, score breakdown, state details"""
    print("\n=== Test: Enhanced Features ===")
    passed = 0
    total = 0

    # Bot status with distance
    total += 1
    from src.execution.alert import TelegramAlert
    alert = TelegramAlert.__new__(TelegramAlert)
    data = {'fear_greed': 13, 'btc_change_24h': -0.5, 'bot_alpha_status': 'near'}
    section = alert._build_bot_status_section(data)
    assert '🟡' in section  # near icon
    assert 'あと3' in section or 'あと' in section  # distance to threshold
    print(f"  ✅ Bot status with distance (Alpha near)")
    passed += 1

    total += 1
    data2 = {'fear_greed': 60, 'btc_change_24h': 2.0, 'bot_alpha_status': 'waiting'}
    section2 = alert._build_bot_status_section(data2)
    assert '🟢' in section2  # MeanRevert active
    assert 'WeakShort' in section2
    assert 'Scalp' in section2
    print(f"  ✅ Bot status with multiple bots")
    passed += 1

    # Score breakdown
    total += 1
    from src.core.state import SymbolState
    s = SymbolState(symbol='TEST/USDT:USDT')
    s.tier1_score = 60
    s.tier2_score = 30
    s.tier1_details = {
        'L02': {'score': 20}, 'L03': {'score': 15}, 'L09': {'score': 10},
        'L17': {'score': 10}, 'L_alpha': {'score': 5}
    }
    s.tier2_details = {
        'L08': {'score': 20}, 'L10': {'score': 15}, 'L13': {'score': -5}
    }
    breakdown = alert._score_breakdown(s)
    assert '聖域+20' in breakdown
    assert '出来高+15' in breakdown
    assert 'FR+20' in breakdown
    assert '清算-5' in breakdown
    print(f"  ✅ Score breakdown: {breakdown}")
    passed += 1

    # Matching bots
    total += 1
    s.btc_correlation = 0.3
    s.btc_alpha = 5.0
    bots = alert._matching_bots(s, fg=35)
    assert 'Surge' in bots
    print(f"  ✅ Matching bots: {bots}")
    passed += 1

    total += 1
    bots2 = alert._matching_bots(s, fg=60)
    assert 'MeanRevert' in bots2
    assert 'WeakShort' in bots2
    print(f"  ✅ Matching bots fg=60: {bots2}")
    passed += 1

    # State details persist
    total += 1
    assert hasattr(s, 'tier1_details')
    assert hasattr(s, 'tier2_details')
    assert s.tier1_details['L02']['score'] == 20
    print(f"  ✅ SymbolState has tier details")
    passed += 1

    # Trigger analysis (enhanced format)
    total += 1
    from src.core.commentary import Commentary
    tc = Commentary.trigger_comment('BTC 4h -9.0%')
    assert '市場意味' in tc
    assert 'トレンド転換' in tc
    assert '監視' in tc
    assert '回避' in tc
    print(f"  ✅ Trigger analysis enhanced: {tc[:60]}...")
    passed += 1

    total += 1
    tc2 = Commentary.trigger_comment('OI 1h +18.0%')
    assert '清算連鎖' in tc2
    print(f"  ✅ Trigger analysis OI")
    passed += 1

    # Market premise
    total += 1
    data3 = {'btc_price': 82500, 'btc_change_24h': 1.5, 'fear_greed': 35,
             'btc_dominance': 61.2, 'regime': 'B', 'regime_action': 'アルト祭り'}
    premise = alert._build_market_premise(data3)
    assert '$82,500' in premise
    assert 'F&amp;G 35' in premise
    assert 'Pattern B' in premise
    print(f"  ✅ Market premise header")
    passed += 1

    print(f"\n  Enhanced Features: {passed}/{total} passed")
    return passed, total


if __name__ == '__main__':
    total_passed = 0
    total_tests = 0

    p, t = test_commentary()
    total_passed += p
    total_tests += t

    p, t = test_veto()
    total_passed += p
    total_tests += t

    p, t = test_alert_imports()
    total_passed += p
    total_tests += t

    p, t = test_enhanced_features()
    total_passed += p
    total_tests += t

    print(f"\n{'='*50}")
    print(f"TOTAL: {total_passed}/{total_tests} passed")
    if total_passed == total_tests:
        print("ALL TESTS PASSED ✅")
    else:
        print(f"FAILURES: {total_tests - total_passed} ❌")
        sys.exit(1)
