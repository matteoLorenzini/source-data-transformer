<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
    <xsl:output method="xml" encoding="UTF-8" indent="yes" />
    <xsl:param name="output_mode" select="'main'" />

    <xsl:template match="/">
        <xsl:choose>
            <xsl:when test="$output_mode = 'csv'">
                <xsl:call-template name="csv-output" />
            </xsl:when>
            <xsl:when test="$output_mode = 'relations'">
                <scheda />
            </xsl:when>
            <xsl:otherwise>
                <xsl:call-template name="main-output" />
            </xsl:otherwise>
        </xsl:choose>
    </xsl:template>

    <xsl:template name="main-output">
        <scheda>
            <xsl:for-each select="/source/rows/row[normalize-space(cell[@key='NAME_SURNAME'][1])]">
                <row index="{@index}">
                    <xsl:for-each select="cell">
                        <xsl:element name="{@tag}">
                            <xsl:call-template name="export-value">
                                <xsl:with-param name="key" select="@key" />
                                <xsl:with-param name="text" select="string(.)" />
                            </xsl:call-template>
                        </xsl:element>
                    </xsl:for-each>
                    <xsl:if test="entities/entity">
                        <CRM_Entities>
                            <xsl:apply-templates select="entities/entity" mode="crm" />
                        </CRM_Entities>
                    </xsl:if>
                </row>
            </xsl:for-each>
        </scheda>
    </xsl:template>

    <xsl:template name="csv-output">
        <csv>
            <xsl:if test="/source/columns/column">
                <row>
                    <xsl:for-each select="/source/columns/column">
                        <cell><xsl:value-of select="normalize-space(.)" /></cell>
                    </xsl:for-each>
                </row>
            </xsl:if>
            <xsl:for-each select="/source/rows/row[normalize-space(cell[@key='NAME_SURNAME'][1])]">
                <row>
                    <xsl:for-each select="cell">
                        <cell>
                            <xsl:call-template name="export-value">
                                <xsl:with-param name="key" select="@key" />
                                <xsl:with-param name="text" select="string(.)" />
                            </xsl:call-template>
                        </cell>
                    </xsl:for-each>
                </row>
            </xsl:for-each>
        </csv>
    </xsl:template>

    <xsl:template name="export-value">
        <xsl:param name="key" />
        <xsl:param name="text" />
        <!-- Google Sheets clipboard exports can prefix a cell with an HTML comment holding CSS -->
        <xsl:variable name="cleaned">
            <xsl:choose>
                <xsl:when test="starts-with(normalize-space($text), '&lt;!--') and contains($text, '--&gt;')">
                    <xsl:value-of select="substring-after($text, '--&gt;')" />
                </xsl:when>
                <xsl:otherwise><xsl:value-of select="$text" /></xsl:otherwise>
            </xsl:choose>
        </xsl:variable>
        <xsl:variable name="trimmed" select="normalize-space(string($cleaned))" />
        <xsl:choose>
            <!-- Excel placeholder 0 / 0.0 in place and date columns means "unknown" -->
            <xsl:when test="($key='BIRTH_PLACE' or $key='BIRTH_DATE' or $key='DEATH_PLACE' or $key='DEATH_DATE')
                            and ($trimmed='0' or $trimmed='0.0')" />
            <!-- Biography keeps its paragraph breaks -->
            <xsl:when test="$key='BIOGRAPHY'"><xsl:value-of select="$cleaned" /></xsl:when>
            <xsl:otherwise><xsl:value-of select="$trimmed" /></xsl:otherwise>
        </xsl:choose>
    </xsl:template>

    <!-- CIDOC-CRM rendering of extracted entities; each keeps its source field and verbatim context -->
    <xsl:template match="entity[@type='person']" mode="crm">
        <E21_Person source_field="{../@field}">
            <P1_is_identified_by><xsl:value-of select="value" /></P1_is_identified_by>
            <P3_has_note><xsl:value-of select="context" /></P3_has_note>
        </E21_Person>
    </xsl:template>

    <xsl:template match="entity[@type='place']" mode="crm">
        <E53_Place source_field="{../@field}">
            <P1_is_identified_by><xsl:value-of select="value" /></P1_is_identified_by>
            <P3_has_note><xsl:value-of select="context" /></P3_has_note>
        </E53_Place>
    </xsl:template>

    <xsl:template match="entity[@type='organization']" mode="crm">
        <E74_Group source_field="{../@field}">
            <P1_is_identified_by><xsl:value-of select="value" /></P1_is_identified_by>
            <P3_has_note><xsl:value-of select="context" /></P3_has_note>
        </E74_Group>
    </xsl:template>

    <xsl:template match="entity[@type='date']" mode="crm">
        <E52_Time-Span source_field="{../@field}">
            <P78_is_identified_by><xsl:value-of select="value" /></P78_is_identified_by>
            <xsl:if test="from"><P82a_begin_of_the_begin><xsl:value-of select="from" /></P82a_begin_of_the_begin></xsl:if>
            <xsl:if test="to"><P82b_end_of_the_end><xsl:value-of select="to" /></P82b_end_of_the_end></xsl:if>
            <P3_has_note><xsl:value-of select="context" /></P3_has_note>
        </E52_Time-Span>
    </xsl:template>

    <xsl:template match="entity[@type='work']" mode="crm">
        <E73_Information_Object source_field="{../@field}">
            <P1_is_identified_by><xsl:value-of select="value" /></P1_is_identified_by>
            <xsl:if test="url">
                <P48_has_preferred_identifier><E42_Identifier><xsl:value-of select="url" /></E42_Identifier></P48_has_preferred_identifier>
            </xsl:if>
            <xsl:if test="from or to">
                <P94i_was_created_by>
                    <E65_Creation><xsl:call-template name="time-span" /></E65_Creation>
                </P94i_was_created_by>
            </xsl:if>
            <P3_has_note><xsl:value-of select="context" /></P3_has_note>
        </E73_Information_Object>
    </xsl:template>

    <xsl:template match="entity[@type='role']" mode="crm">
        <E7_Activity source_field="{../@field}">
            <P2_has_type>
                <E55_Type><P1_is_identified_by><xsl:value-of select="value" /></P1_is_identified_by></E55_Type>
            </P2_has_type>
            <P14_carried_out_by>
                <E21_Person>
                    <P1_is_identified_by><xsl:value-of select="normalize-space(../../cell[@key='NAME_SURNAME'][1])" /></P1_is_identified_by>
                    <xsl:if test="organization">
                        <P107i_is_current_or_former_member_of>
                            <E74_Group><P1_is_identified_by><xsl:value-of select="organization" /></P1_is_identified_by></E74_Group>
                        </P107i_is_current_or_former_member_of>
                    </xsl:if>
                </E21_Person>
            </P14_carried_out_by>
            <xsl:call-template name="took-place-at" />
            <xsl:call-template name="time-span" />
            <P3_has_note><xsl:value-of select="context" /></P3_has_note>
        </E7_Activity>
    </xsl:template>

    <xsl:template match="entity[@type='event']" mode="crm">
        <E5_Event source_field="{../@field}">
            <P1_is_identified_by><xsl:value-of select="value" /></P1_is_identified_by>
            <xsl:if test="organization">
                <P11_had_participant>
                    <E74_Group><P1_is_identified_by><xsl:value-of select="organization" /></P1_is_identified_by></E74_Group>
                </P11_had_participant>
            </xsl:if>
            <xsl:call-template name="took-place-at" />
            <xsl:call-template name="time-span" />
            <P3_has_note><xsl:value-of select="context" /></P3_has_note>
        </E5_Event>
    </xsl:template>

    <xsl:template name="took-place-at">
        <xsl:if test="place">
            <P7_took_place_at>
                <E53_Place><P1_is_identified_by><xsl:value-of select="place" /></P1_is_identified_by></E53_Place>
            </P7_took_place_at>
        </xsl:if>
    </xsl:template>

    <xsl:template name="time-span">
        <xsl:if test="from or to">
            <P4_has_time-span>
                <E52_Time-Span>
                    <xsl:if test="from"><P82a_begin_of_the_begin><xsl:value-of select="from" /></P82a_begin_of_the_begin></xsl:if>
                    <xsl:if test="to"><P82b_end_of_the_end><xsl:value-of select="to" /></P82b_end_of_the_end></xsl:if>
                </E52_Time-Span>
            </P4_has_time-span>
        </xsl:if>
    </xsl:template>
</xsl:stylesheet>
