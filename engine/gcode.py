"""Neutral move list -> G21 G90 absolute G-code (LNC post comes later)."""


def moves_to_gcode(moves, spindle_rpm=7500, tool_comment=None,
                   feed_rapid_note="G1 feeds carry F words; G0 is rapid"):
    out = ["G21", "G90", "G94", "G17"]
    if tool_comment:
        out.append("(%s)" % tool_comment)
    out.append("(ENGINE ROUGH)")
    out.append("S%d M3" % spindle_rpm)
    for mv in moves:
        if mv["g"] == 0:
            bits = []
            if mv.get("x") is not None:
                bits.append("X%.4f" % mv["x"])
            if mv.get("y") is not None:
                bits.append("Y%.4f" % mv["y"])
            if mv.get("z") is not None:
                bits.append("Z%.4f" % mv["z"])
            out.append("G0 " + " ".join(bits))
        else:
            bits = []
            if mv.get("x") is not None:
                bits.append("X%.4f" % mv["x"])
            if mv.get("y") is not None:
                bits.append("Y%.4f" % mv["y"])
            if mv.get("z") is not None:
                bits.append("Z%.4f" % mv["z"])
            if mv.get("f"):
                bits.append("F%.0f" % mv["f"])
            out.append("G1 " + " ".join(bits))
    out.append("G0 Z%.4f" % max((m["z"] for m in moves if m.get("z") is not None
                                  and m["g"] == 0), default=5.0))
    out.append("M5")
    out.append("M30")
    return "\n".join(out) + "\n"
