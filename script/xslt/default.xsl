<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
    <xsl:output method="xml" encoding="UTF-8" indent="yes" />
    <xsl:param name="output_mode" select="'main'" />
    <xsl:variable name="resource_uri" select="'http://www.lynx.com/resource/cultural-heritage-object/'" />

    <xsl:key name="project_by_id" match="source/rows/row/cell[@key='PROJECT_ID']" use="normalize-space(.)" />
    <xsl:key name="row_by_unique_id" match="source/rows/row" use="normalize-space(cell[@key='UNIQUE_ID'][1])" />

    <xsl:template match="/">
        <xsl:choose>
            <xsl:when test="$output_mode = 'csv'">
                <xsl:call-template name="csv-output" />
            </xsl:when>
            <xsl:when test="$output_mode = 'relations'">
                <xsl:call-template name="relations-output" />
            </xsl:when>
            <xsl:otherwise>
                <xsl:call-template name="main-output" />
            </xsl:otherwise>
        </xsl:choose>
    </xsl:template>

    <xsl:template name="main-output">
        <scheda>
            <xsl:for-each select="/source/rows/row">
                <row index="{@index}">
                    <xsl:for-each select="cell[not(@key='ATTACHES_TO' or @key='ATTACHES_TO_UNIQUE_ID' or @key='SIMILAR_TO' or @key='SIMILAR_TO_UNIQUE_ID')]">
                        <xsl:variable name="value">
                            <xsl:call-template name="export-value">
                                <xsl:with-param name="key" select="@key" />
                                <xsl:with-param name="text" select="string(.)" />
                            </xsl:call-template>
                        </xsl:variable>
                        <xsl:element name="{@tag}">
                            <xsl:choose>
                                <xsl:when test="@key='DISCRIMINANTE_TECNICA' or @key='TECHNICAL_DIAGNOSTIC_FEATURES'">
                                    <xsl:call-template name="emit-labels">
                                        <xsl:with-param name="text" select="string($value)" />
                                    </xsl:call-template>
                                </xsl:when>
                                <xsl:otherwise>
                                    <xsl:value-of select="$value" />
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
                        <cell>
                            <xsl:call-template name="normalize-cell">
                                <xsl:with-param name="text" select="string(.)" />
                            </xsl:call-template>
                        </cell>
                    </xsl:for-each>
                </row>
            </xsl:if>
            <xsl:for-each select="/source/rows/row">
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

    <xsl:template name="relations-output">
        <scheda>
            <xsl:for-each select="/source/rows/row">
                <xsl:variable name="source_id" select="normalize-space(cell[@key='UNIQUE_ID'][1])" />
                <xsl:variable name="attaches_cell" select="cell[@key='ATTACHES_TO'][last()]" />
                <xsl:variable name="similar_cell" select="cell[@key='SIMILAR_TO'][last()]" />
                <xsl:variable name="attaches_text">
                    <xsl:call-template name="relation-values">
                        <xsl:with-param name="text" select="string($attaches_cell)" />
                        <xsl:with-param name="source_id" select="$source_id" />
                        <xsl:with-param name="mode" select="'labels'" />
                    </xsl:call-template>
                </xsl:variable>
                <xsl:variable name="similar_text">
                    <xsl:call-template name="relation-values">
                        <xsl:with-param name="text" select="string($similar_cell)" />
                        <xsl:with-param name="source_id" select="$source_id" />
                        <xsl:with-param name="mode" select="'labels'" />
                    </xsl:call-template>
                </xsl:variable>
                <xsl:if test="string($attaches_text) or string($similar_text)">
                    <row index="{@index}">
                        <Unique_ID>
                            <xsl:call-template name="prefixed-id">
                                <xsl:with-param name="value" select="$source_id" />
                            </xsl:call-template>
                        </Unique_ID>
                        <xsl:variable name="attaches_tag">
                            <xsl:choose>
                                <xsl:when test="$attaches_cell"><xsl:value-of select="$attaches_cell/@tag" /></xsl:when>
                                <xsl:otherwise>Attaches_to</xsl:otherwise>
                            </xsl:choose>
                        </xsl:variable>
                        <xsl:element name="{string($attaches_tag)}"><xsl:value-of select="$attaches_text" /></xsl:element>
                        <xsl:element name="{concat(string($attaches_tag), '_unique_id')}">
                            <xsl:call-template name="relation-values">
                                <xsl:with-param name="text" select="string($attaches_cell)" />
                                <xsl:with-param name="source_id" select="$source_id" />
                                <xsl:with-param name="mode" select="'ids'" />
                            </xsl:call-template>
                        </xsl:element>
                        <xsl:variable name="similar_tag">
                            <xsl:choose>
                                <xsl:when test="$similar_cell"><xsl:value-of select="$similar_cell/@tag" /></xsl:when>
                                <xsl:otherwise>Similar_to</xsl:otherwise>
                            </xsl:choose>
                        </xsl:variable>
                        <xsl:element name="{string($similar_tag)}"><xsl:value-of select="$similar_text" /></xsl:element>
                        <xsl:element name="{concat(string($similar_tag), '_unique_id')}">
                            <xsl:call-template name="relation-values">
                                <xsl:with-param name="text" select="string($similar_cell)" />
                                <xsl:with-param name="source_id" select="$source_id" />
                                <xsl:with-param name="mode" select="'ids'" />
                            </xsl:call-template>
                        </xsl:element>
                    </row>
                </xsl:if>
            </xsl:for-each>
        </scheda>
    </xsl:template>

    <xsl:template name="export-value">
        <xsl:param name="key" />
        <xsl:param name="text" />
        <xsl:variable name="normalized">
            <xsl:call-template name="normalize-cell">
                <xsl:with-param name="text" select="$text" />
            </xsl:call-template>
        </xsl:variable>
        <xsl:choose>
            <xsl:when test="$key='PLACE_OF_DISCOVERY' and string($normalized)='Sperlonga'">1</xsl:when>
            <xsl:when test="$key='PLACE_OF_DISCOVERY' and string($normalized)='Sabaudia'">2</xsl:when>
            <xsl:when test="$key='SITE_OF_DISCOVERY' and string($normalized)='Villa di Tiberio'">1</xsl:when>
            <xsl:when test="$key='SITE_OF_DISCOVERY' and string($normalized)='Villa di Domiziano'">2</xsl:when>
            <xsl:otherwise><xsl:value-of select="$normalized" /></xsl:otherwise>
        </xsl:choose>
    </xsl:template>

    <xsl:template name="normalize-cell">
        <xsl:param name="text" />
        <xsl:choose>
            <xsl:when test="contains($text, '&#10;')">
                <xsl:call-template name="normalize-lines">
                    <xsl:with-param name="text" select="$text" />
                    <xsl:with-param name="has_value" select="'no'" />
                </xsl:call-template>
            </xsl:when>
            <xsl:otherwise><xsl:value-of select="$text" /></xsl:otherwise>
        </xsl:choose>
    </xsl:template>

    <xsl:template name="normalize-lines">
        <xsl:param name="text" />
        <xsl:param name="has_value" />
        <xsl:variable name="line">
            <xsl:choose>
                <xsl:when test="contains($text, '&#10;')"><xsl:value-of select="normalize-space(substring-before($text, '&#10;'))" /></xsl:when>
                <xsl:otherwise><xsl:value-of select="normalize-space($text)" /></xsl:otherwise>
            </xsl:choose>
        </xsl:variable>
        <xsl:if test="string($line)">
            <xsl:if test="$has_value='yes'">; </xsl:if>
            <xsl:value-of select="$line" />
        </xsl:if>
        <xsl:if test="contains($text, '&#10;')">
            <xsl:variable name="next_has_value">
                <xsl:choose>
                    <xsl:when test="$has_value='yes' or string($line)">yes</xsl:when>
                    <xsl:otherwise>no</xsl:otherwise>
                </xsl:choose>
            </xsl:variable>
            <xsl:call-template name="normalize-lines">
                <xsl:with-param name="text" select="substring-after($text, '&#10;')" />
                <xsl:with-param name="has_value" select="string($next_has_value)" />
            </xsl:call-template>
        </xsl:if>
    </xsl:template>

    <xsl:template name="emit-labels">
        <xsl:param name="text" />
        <xsl:variable name="list" select="translate($text, ',', ';')" />
        <xsl:variable name="label">
            <xsl:choose>
                <xsl:when test="contains($list, ';')"><xsl:value-of select="normalize-space(substring-before($list, ';'))" /></xsl:when>
                <xsl:otherwise><xsl:value-of select="normalize-space($list)" /></xsl:otherwise>
            </xsl:choose>
        </xsl:variable>
        <xsl:if test="string($label)">
            <value><xsl:value-of select="$label" /></value>
        </xsl:if>
        <xsl:if test="contains($list, ';')">
            <xsl:call-template name="emit-labels">
                <xsl:with-param name="text" select="substring-after($list, ';')" />
            </xsl:call-template>
        </xsl:if>
    </xsl:template>

    <xsl:template name="prefixed-id">
        <xsl:param name="value" />
        <xsl:variable name="normalized" select="normalize-space($value)" />
        <xsl:if test="$normalized">
            <xsl:choose>
                <xsl:when test="starts-with($normalized, $resource_uri)"><xsl:value-of select="$normalized" /></xsl:when>
                <xsl:otherwise><xsl:value-of select="concat($resource_uri, $normalized)" /></xsl:otherwise>
            </xsl:choose>
        </xsl:if>
    </xsl:template>

    <xsl:template name="relation-values">
        <xsl:param name="text" />
        <xsl:param name="source_id" />
        <xsl:param name="mode" />
        <xsl:param name="has_value" select="'no'" />
        <xsl:variable name="list" select="translate($text, ',', ';')" />
        <xsl:variable name="token">
            <xsl:choose>
                <xsl:when test="contains($list, ';')"><xsl:value-of select="normalize-space(substring-before($list, ';'))" /></xsl:when>
                <xsl:otherwise><xsl:value-of select="normalize-space($list)" /></xsl:otherwise>
            </xsl:choose>
        </xsl:variable>
        <xsl:variable name="target_id" select="normalize-space(key('project_by_id', string($token))[1]/../cell[@key='UNIQUE_ID'][1])" />
        <xsl:variable name="keep">
            <xsl:choose>
                <xsl:when test="not(string($token))">no</xsl:when>
                <xsl:when test="not(string($target_id))">yes</xsl:when>
                <xsl:when test="not(string($source_id))">yes</xsl:when>
                <xsl:when test="$source_id = $target_id">no</xsl:when>
                <xsl:when test="translate($source_id, '0123456789', '')='' and translate($target_id, '0123456789', '')=''">
                    <xsl:if test="number($source_id) &lt; number($target_id)">yes</xsl:if>
                </xsl:when>
                <xsl:otherwise>
                    <xsl:variable name="first_id">
                        <xsl:for-each select="key('row_by_unique_id', string($source_id)) | key('row_by_unique_id', string($target_id))">
                            <xsl:sort select="string(cell[@key='UNIQUE_ID'][1])" data-type="text" />
                            <xsl:if test="position()=1"><xsl:value-of select="normalize-space(cell[@key='UNIQUE_ID'][1])" /></xsl:if>
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
                <xsl:when test="$mode='labels'"><xsl:value-of select="$token" /></xsl:when>
                <xsl:otherwise><xsl:value-of select="concat($resource_uri, $target_id)" /></xsl:otherwise>
            </xsl:choose>
        </xsl:if>
        <xsl:if test="contains($list, ';')">
            <xsl:variable name="next_has_value">
                <xsl:choose>
                    <xsl:when test="$has_value='yes' or $emits_value">yes</xsl:when>
                    <xsl:otherwise>no</xsl:otherwise>
                </xsl:choose>
            </xsl:variable>
            <xsl:call-template name="relation-values">
                <xsl:with-param name="text" select="substring-after($list, ';')" />
                <xsl:with-param name="source_id" select="$source_id" />
                <xsl:with-param name="mode" select="$mode" />
                <xsl:with-param name="has_value" select="string($next_has_value)" />
            </xsl:call-template>
        </xsl:if>
    </xsl:template>
</xsl:stylesheet>