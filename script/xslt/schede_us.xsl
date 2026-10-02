<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
    <xsl:import href="default.xsl" />
    <xsl:output method="xml" encoding="UTF-8" indent="yes" />
    <xsl:variable name="stratigraphic_unit_uri" select="'http://www.lynx.com/resource/stratigraphic-unit/'" />

    <xsl:key name="us_by_id" match="source/rows/row/cell[@key='US_ID']" use="format-number(number(normalize-space(.)), '0.################')" />

    <xsl:template match="/">
        <xsl:if test="not(/source/columns/column[@key='UNIQUE_ID'])">
            <xsl:message terminate="yes">The schede_us stylesheet requires a Unique_ID column in the workbook.</xsl:message>
        </xsl:if>
        <xsl:choose>
            <xsl:when test="$output_mode='csv'"><xsl:call-template name="csv-output" /></xsl:when>
            <xsl:when test="$output_mode='relations'"><xsl:call-template name="relations-output" /></xsl:when>
            <xsl:otherwise><xsl:call-template name="main-output" /></xsl:otherwise>
        </xsl:choose>
    </xsl:template>

    <xsl:template name="main-output">
        <scheda>
            <xsl:for-each select="/source/rows/row">
                <row index="{@index}">
                    <xsl:variable name="type_cells" select="cell[(@key='NATURALE' or @key='ARTIFICIALE' or @key='POSITIVA' or @key='NEGATIVA') and normalize-space(.)='X']" />
                    <xsl:if test="$type_cells">
                        <Tipologia>
                            <xsl:for-each select="$type_cells">
                                <value><xsl:value-of select="@tag" /></value>
                            </xsl:for-each>
                        </Tipologia>
                    </xsl:if>
                    <xsl:for-each select="cell[starts-with(@key, 'LOCALIT') and normalize-space(.)]">
                        <Luogo>
                            <xsl:variable name="text" select="normalize-space(string(.))" />
                            <xsl:variable name="place">
                                <xsl:choose>
                                    <xsl:when test="contains($text, '-')"><xsl:value-of select="normalize-space(substring-before($text, '-'))" /></xsl:when>
                                    <xsl:otherwise><xsl:value-of select="$text" /></xsl:otherwise>
                                </xsl:choose>
                            </xsl:variable>
                            <xsl:variable name="site" select="normalize-space(substring-after($text, '-'))" />
                            <place_name>
                                <xsl:choose>
                                    <xsl:when test="$place='Sperlonga'">1</xsl:when>
                                    <xsl:when test="$place='Sabaudia'">2</xsl:when>
                                    <xsl:otherwise><xsl:value-of select="$place" /></xsl:otherwise>
                                </xsl:choose>
                            </place_name>
                            <xsl:if test="contains($text, '-')">
                                <site_name>
                                    <xsl:choose>
                                        <xsl:when test="$site='Villa di Tiberio'">1</xsl:when>
                                        <xsl:when test="$site='Villa di Domiziano'">2</xsl:when>
                                        <xsl:otherwise><xsl:value-of select="$site" /></xsl:otherwise>
                                    </xsl:choose>
                                </site_name>
                            </xsl:if>
                        </Luogo>
                    </xsl:for-each>
                    <xsl:for-each select="cell[not(starts-with(@key, 'LOCALIT')) and not(@key='NATURALE' or @key='ARTIFICIALE' or @key='POSITIVA' or @key='NEGATIVA') and not(starts-with(@key, 'SEQUENZA_FISICA_') or starts-with(@key, 'SEQUENZA_STRATIGRAFICA_'))]">
                        <xsl:variable name="value">
                            <xsl:call-template name="export-value">
                                <xsl:with-param name="key" select="@key" />
                                <xsl:with-param name="text" select="string(.)" />
                            </xsl:call-template>
                        </xsl:variable>
                        <xsl:element name="{@tag}">
                            <xsl:choose>
                                <xsl:when test="@key='UNIQUE_ID'">
                                    <xsl:call-template name="normalize-id">
                                        <xsl:with-param name="value" select="string(.)" />
                                    </xsl:call-template>
                                </xsl:when>
                                <xsl:when test="@key='US_ID'">
                                    <xsl:call-template name="normalize-id">
                                        <xsl:with-param name="value" select="string(.)" />
                                    </xsl:call-template>
                                </xsl:when>
                                <xsl:when test="@key='CRITERI_DISTINZIONE' or @key='MODO_FORMAZIONE' or @key='COMPONENTI_INORGANICI' or @key='COMPONENTI_ORGANICI'">
                                    <xsl:call-template name="emit-labels">
                                        <xsl:with-param name="text" select="string($value)" />
                                    </xsl:call-template>
                                </xsl:when>
                                <xsl:otherwise>
                                    <xsl:call-template name="normalize-integer-decimal">
                                        <xsl:with-param name="value" select="string($value)" />
                                    </xsl:call-template>
                                </xsl:otherwise>
                            </xsl:choose>
                        </xsl:element>
                    </xsl:for-each>
                </row>
            </xsl:for-each>
        </scheda>
    </xsl:template>

    <xsl:template name="csv-output">
        <csv>
            <xsl:if test="/source/columns/column">
                <row>
                    <xsl:for-each select="/source/columns/column">
                        <cell><xsl:value-of select="." /></cell>
                    </xsl:for-each>
                </row>
            </xsl:if>
            <xsl:for-each select="/source/rows/row">
                <row>
                    <xsl:for-each select="cell">
                        <cell>
                            <xsl:choose>
                                <xsl:when test="(@key='NATURALE' or @key='ARTIFICIALE' or @key='POSITIVA' or @key='NEGATIVA') and normalize-space(.)='X'">
                                    <xsl:value-of select="@tag" />
                                </xsl:when>
                                <xsl:when test="@key='UNIQUE_ID' or @key='US_ID'">
                                    <xsl:call-template name="normalize-id">
                                        <xsl:with-param name="value" select="string(.)" />
                                    </xsl:call-template>
                                </xsl:when>
                                <xsl:otherwise>
                                    <xsl:variable name="value">
                                        <xsl:call-template name="export-value">
                                            <xsl:with-param name="key" select="@key" />
                                            <xsl:with-param name="text" select="string(.)" />
                                        </xsl:call-template>
                                    </xsl:variable>
                                    <xsl:call-template name="normalize-integer-decimal">
                                        <xsl:with-param name="value" select="string($value)" />
                                    </xsl:call-template>
                                </xsl:otherwise>
                            </xsl:choose>
                        </cell>
                    </xsl:for-each>
                </row>
            </xsl:for-each>
        </csv>
    </xsl:template>

    <xsl:template name="relations-output">
        <xsl:variable name="relation_columns" select="/source/columns/column[starts-with(@key, 'SEQUENZA_FISICA_') or starts-with(@key, 'SEQUENZA_STRATIGRAFICA_')]" />
        <scheda>
            <xsl:for-each select="/source/rows/row">
                <xsl:variable name="source_row" select="." />
                <xsl:variable name="source_id">
                    <xsl:call-template name="normalize-id">
                        <xsl:with-param name="value" select="string(cell[@key='US_ID'][1])" />
                    </xsl:call-template>
                </xsl:variable>
                <xsl:variable name="source_unique_id" select="string(cell[@key='UNIQUE_ID'][1])" />
                <xsl:if test="cell[(starts-with(@key, 'SEQUENZA_FISICA_') or starts-with(@key, 'SEQUENZA_STRATIGRAFICA_')) and normalize-space(.)]">
                    <row index="{@index}">
                        <Unique_ID>
                            <xsl:call-template name="prefixed-us-id">
                                <xsl:with-param name="value" select="string($source_unique_id)" />
                            </xsl:call-template>
                        </Unique_ID>
                        <xsl:for-each select="$relation_columns">
                            <xsl:variable name="column_key" select="@key" />
                            <xsl:variable name="relation_cell" select="$source_row/cell[@key=$column_key][1]" />
                            <xsl:element name="{$relation_cell/@tag}">
                                <xsl:call-template name="relation-values-us">
                                    <xsl:with-param name="text" select="string($relation_cell)" />
                                    <xsl:with-param name="source_row" select="$source_row" />
                                    <xsl:with-param name="source_id" select="$source_id" />
                                    <xsl:with-param name="mode" select="'labels'" />
                                </xsl:call-template>
                            </xsl:element>
                            <xsl:element name="{concat($relation_cell/@tag, '_unique_id')}">
                                <xsl:call-template name="relation-values-us">
                                    <xsl:with-param name="text" select="string($relation_cell)" />
                                    <xsl:with-param name="source_row" select="$source_row" />
                                    <xsl:with-param name="source_id" select="$source_id" />
                                    <xsl:with-param name="mode" select="'ids'" />
                                </xsl:call-template>
                            </xsl:element>
                        </xsl:for-each>
                    </row>
                </xsl:if>
            </xsl:for-each>
        </scheda>
    </xsl:template>

    <xsl:template name="relation-values-us">
        <xsl:param name="text" />
        <xsl:param name="source_row" />
        <xsl:param name="source_id" />
        <xsl:param name="mode" />
        <xsl:param name="has_value" select="'no'" />
        <xsl:variable name="list" select="translate($text, ',&#10;&#13;', ';;;')" />
        <xsl:variable name="token">
            <xsl:choose>
                <xsl:when test="contains($list, ';')"><xsl:value-of select="normalize-space(substring-before($list, ';'))" /></xsl:when>
                <xsl:otherwise><xsl:value-of select="normalize-space($list)" /></xsl:otherwise>
            </xsl:choose>
        </xsl:variable>
        <xsl:variable name="normalized_token">
            <xsl:call-template name="normalize-id">
                <xsl:with-param name="value" select="string($token)" />
            </xsl:call-template>
        </xsl:variable>
        <xsl:variable name="target_row" select="key('us_by_id', string($normalized_token))[1]/.." />
        <xsl:variable name="target_id" select="string($target_row[1]/cell[@key='UNIQUE_ID'][1])" />
        <xsl:variable name="target_us_id">
            <xsl:call-template name="normalize-id">
                <xsl:with-param name="value" select="string($target_row[1]/cell[@key='US_ID'][1])" />
            </xsl:call-template>
        </xsl:variable>
        <xsl:variable name="keep">
            <xsl:choose>
                <xsl:when test="not(string($token))">no</xsl:when>
                <xsl:when test="not(string($target_us_id))">yes</xsl:when>
                <xsl:when test="not(string($source_id))">yes</xsl:when>
                <xsl:when test="$source_id=string($target_us_id)">no</xsl:when>
                <xsl:when test="translate($source_id, '0123456789-', '')='' and translate(string($target_us_id), '0123456789-', '')=''">
                    <xsl:if test="number($source_id) &lt; number($target_us_id)">yes</xsl:if>
                </xsl:when>
                <xsl:otherwise>
                    <xsl:variable name="first_id">
                        <xsl:for-each select="$source_row/cell[@key='US_ID'][1] | $target_row[1]/cell[@key='US_ID'][1]">
                            <xsl:sort select="string(.)" data-type="text" />
                            <xsl:if test="position()=1">
                                <xsl:call-template name="normalize-id">
                                    <xsl:with-param name="value" select="string(.)" />
                                </xsl:call-template>
                            </xsl:if>
                        </xsl:for-each>
                    </xsl:variable>
                    <xsl:if test="string($first_id)=$source_id">yes</xsl:if>
                </xsl:otherwise>
            </xsl:choose>
        </xsl:variable>
        <xsl:variable name="emits_value" select="string($keep)='yes' and ($mode='labels' or string($target_id))" />
        <xsl:if test="$emits_value">
            <xsl:if test="$has_value='yes'">; </xsl:if>
            <xsl:choose>
                <xsl:when test="$mode='labels'"><xsl:value-of select="$normalized_token" /></xsl:when>
                <xsl:otherwise>
                    <xsl:call-template name="prefixed-us-id">
                        <xsl:with-param name="value" select="string($target_id)" />
                    </xsl:call-template>
                </xsl:otherwise>
            </xsl:choose>
        </xsl:if>
        <xsl:if test="contains($list, ';')">
            <xsl:variable name="next_has_value">
                <xsl:choose>
                    <xsl:when test="$has_value='yes' or $emits_value">yes</xsl:when>
                    <xsl:otherwise>no</xsl:otherwise>
                </xsl:choose>
            </xsl:variable>
            <xsl:call-template name="relation-values-us">
                <xsl:with-param name="text" select="substring-after($list, ';')" />
                <xsl:with-param name="source_row" select="$source_row" />
                <xsl:with-param name="source_id" select="$source_id" />
                <xsl:with-param name="mode" select="$mode" />
                <xsl:with-param name="has_value" select="string($next_has_value)" />
            </xsl:call-template>
        </xsl:if>
    </xsl:template>

    <xsl:template name="normalize-id">
        <xsl:param name="value" />
        <xsl:variable name="normalized" select="normalize-space($value)" />
        <xsl:choose>
            <xsl:when test="$normalized and number($normalized)=number($normalized)">
                <xsl:value-of select="format-number(number($normalized), '0.################')" />
            </xsl:when>
            <xsl:otherwise><xsl:value-of select="$normalized" /></xsl:otherwise>
        </xsl:choose>
    </xsl:template>

    <xsl:template name="normalize-integer-decimal">
        <xsl:param name="value" />
        <xsl:variable name="normalized" select="normalize-space($value)" />
        <xsl:choose>
            <xsl:when test="contains($normalized, '.') and substring-after($normalized, '.')='0' and number($normalized)=number($normalized)">
                <xsl:value-of select="substring($normalized, 1, string-length($normalized) - 2)" />
            </xsl:when>
            <xsl:otherwise><xsl:value-of select="$value" /></xsl:otherwise>
        </xsl:choose>
    </xsl:template>

    <xsl:template name="prefixed-us-id">
        <xsl:param name="value" />
        <xsl:variable name="normalized">
            <xsl:call-template name="normalize-id">
                <xsl:with-param name="value" select="$value" />
            </xsl:call-template>
        </xsl:variable>
        <xsl:if test="string($normalized)">
            <xsl:choose>
                <xsl:when test="starts-with(string($normalized), $stratigraphic_unit_uri)"><xsl:value-of select="$normalized" /></xsl:when>
                <xsl:when test="starts-with(string($normalized), 'http://www.lynx.com/resource/cultural-heritage-object/')">
                    <xsl:variable name="legacy_id">
                        <xsl:call-template name="normalize-id">
                            <xsl:with-param name="value" select="substring-after(string($normalized), 'http://www.lynx.com/resource/cultural-heritage-object/')" />
                        </xsl:call-template>
                    </xsl:variable>
                    <xsl:value-of select="concat($stratigraphic_unit_uri, string($legacy_id))" />
                </xsl:when>
                <xsl:otherwise><xsl:value-of select="concat($stratigraphic_unit_uri, string($normalized))" /></xsl:otherwise>
            </xsl:choose>
        </xsl:if>
    </xsl:template>
</xsl:stylesheet>