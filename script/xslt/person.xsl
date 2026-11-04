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
                        <Entities>
                            <xsl:apply-templates select="entities/entity" mode="plain" />
                        </Entities>
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

    <!-- Extracted entity: element named after its type (Person, Place, Date, ...), with its source field and verbatim context -->
    <xsl:template match="entity" mode="plain">
        <xsl:element name="{concat(translate(substring(@type, 1, 1), 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), substring(@type, 2))}">
            <xsl:attribute name="source_field"><xsl:value-of select="../@field" /></xsl:attribute>
            <xsl:for-each select="value | from | to | place | organization | url | context">
                <xsl:element name="{concat(translate(substring(name(), 1, 1), 'abcdefghijklmnopqrstuvwxyz', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'), substring(name(), 2))}">
                    <xsl:value-of select="." />
                </xsl:element>
            </xsl:for-each>
        </xsl:element>
    </xsl:template>
</xsl:stylesheet>
